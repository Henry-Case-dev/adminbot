# SMART-CORRECTIVE-01 — привязка независимо одобренных срезов (уровень REVIEW)

Дата: 2026-11-14 21:51 +12:00. Автор: PM (unit `pm-bind-slices`).
Основание: независимые review-вердикты по срезам S1-CONTRACT + S2-SOURCEREADER, S3-BUDGET, S5A-LIFECYCLE, S5B-RECOVERY.
Уровень приёмки: **REVIEW** (predeploy, кандидат-связанный). Ни одна строка **не** переведена в `VERIFIED`.

## 1. Что сделано

1. Evidence-артефакты четырёх срезов скопированы байт-в-байт из worktree/веток в рабочее дерево master под те же пути (`plans/features/smart-corrective-01/evidence/<slice>/`). Код и тесты не копировались.
2. В `requirements-map.json` для каждой required-строки одобренных срезов добавлены implementation-evidence (candidate-bound, с ref/observation/artifact_path/artifact_sha256) и review-evidence (`type: review`, `reviewer_role: Reviewer`, `verdict: Approved`, candidate = код-коммит среза).
3. Добавлены `slice_candidate_bindings` в `requirements-map.json` и `slice-graph.json` (по пяти срезам).
4. `candidate_commit` карты оставлен пустым, `deployed_commit` не устанавливался: релизного поезда ещё нет, финальная перепривязка — на release.
5. Прогнаны гейты: plan (0 ошибок) и review по каждому срезу; выводы сохранены в `evidence/gates/`.

## 2. Привязка срезов

| Срез | Код-кандидат | База | Ветка | Review-артефакт (sha256) | Implementation (sha256) |
|---|---|---|---|---|---|
| S1-CONTRACT | `91516d55fb2e436337bf76ec23b99d5f27f175da` | `13884daa32e5cf2a1c05c5c43188ca299f8179f8` | `sc/corrective-s1s2` @ `057b65c9` | `evidence/s1s2/review-r1.md` `ff255a009e6cda7027b9f92eca95df2f03eb6476daaebd7ab16b96ca5bce48c3` | `evidence/s1s2/implementation.md` `3457121a360587c5c2b3c1eddcf99e6cda74c378f2cc3d5aafaf9d3a93a5415e` |
| S2-SOURCEREADER | `91516d55fb2e436337bf76ec23b99d5f27f175da` | `13884daa32e5cf2a1c05c5c43188ca299f8179f8` | `sc/corrective-s1s2` @ `057b65c9` | тот же | тот же |
| S3-BUDGET | `163b8ddd567ec60ea8cb3274a37b10e9297bddd7` | `13884daa32e5cf2a1c05c5c43188ca299f8179f8` | `sc/corrective-s3` @ `bbb30555` | `evidence/s3/review-r1.md` `2be25415e80793515df3e9ee8eded485f274f700c78a2e59ba2c25bf6117987b` | `evidence/s3/implementation.md` `564e103b0a7b654022e992a260ab62624a5c0bbc5198d118d32867ea4d998eb9` |
| S5A-LIFECYCLE | `3ff04f3f6c4476851174e67f1e163db7504a1c9` | `13884daa32e5cf2a1c05c5c43188ca299f8179f8` | `sc/corrective-s5a` @ `e360738b` | `evidence/s5a/review-r1.md` `cb7596a128a52da7dce75f9883ad2f2f0a9f13d07694d0b6c55127d53f752361` | `evidence/s5a/implementation.md` `af78fef075552ddf2127830bc46cd9a7973bfc745680f058dd368ce776ed91e4` |
| S5B-RECOVERY | `a515d09da61aef603fb6b92aa3c7b8341fbe421b` | `sc/corrective-s5a` @ `e360738b` | `sc/corrective-s5b` @ `7d0c6b40` | `evidence/s5b/review-r1.md` `99311a8547d06dd30c4ecffc249ad4e5ab66a7568e6aa294c8412ad6ad2b1ab5` | `evidence/s5b/implementation.md` `90ee337e570248c65f9cd0054e8f041e8e2f793dda19e43b940940ac1b8e670b` |

Worktrees (managed, `WorkspaceData/worktrees`):
`…-90a1abda` (s1s2), `…-8d0575b5` (s3), `…-c89fcb78` (s5a), `…-756d6104` (s5b).

### Отклонение от буквального указания по кандидату S1/S2

В задании был указан код-кандидат `f007da33`. Фактически одобренный Reviewer код — `91516d55`:
`f007da33` — предпоследний код-коммит («remove diagnostic candidate sample cap»), а `91516d55` — одобренный fix «confirm multi-line traceback fragments contiguously» (394 строки `services/source_reader.py` + 146 строк тестов), без которого `SC-SEARCH-CAP-05` остаётся дефектным. Review r2 прямо фиксирует: «Fix 91516d55, branch HEAD 057b65c9». Привязка к `f007da33` дала бы approval на код без одобренного fix; поэтому evidence привязано к `91516d55`, а `057b65c9` (docs/evidence) — tip ветки.
Проверка: `evidence/gates/review-S1-CONTRACT-candidate-f007da33.txt` — 60 ошибок (`no evidence bound to reviewed candidate`), ожидаемо.

## 3. Скопированные артефакты (байт-в-байт) и sha256

| Путь | Байт | sha256 | Статус в ветке |
|---|---:|---|---|
| `evidence/s1s2/implementation.md` | 23327 | `3457121a360587c5c2b3c1eddcf99e6cda74c378f2cc3d5aafaf9d3a93a5415e` | committed, совпадает с blob `057b65c9` |
| `evidence/s1s2/real-tree-search.json` | 5587 | `71c5b42297c0e1e1f8c177bc4a229f364fb6b06460fa87492b7ff1bfb8f165ab` | committed |
| `evidence/s1s2/real-tree-continuation.json` | 3955 | `7d808e03c04a3bad8fc842121938b67ba621732bf5b46da362bc32bd2194ef31` | committed |
| `evidence/s1s2/cleanup-retention.json` | 570 | `f7e5c4d0e27dbe769ec64263f8b9be3149c796f1e76ca5729ae8febe333bff2d` | committed |
| `evidence/s1s2/review-r1.md` | 3144 | `ff255a009e6cda7027b9f92eca95df2f03eb6476daaebd7ab16b96ca5bce48c3` | uncommitted (Reviewer), скопирован из worktree |
| `evidence/s3/implementation.md` | 21887 | `564e103b0a7b654022e992a260ab62624a5c0bbc5198d118d32867ea4d998eb9` | committed, совпадает с blob `bbb30555` |
| `evidence/s3/cleanup-retention.json` | 574 | `212929a13eb41fa790b18461565ca1224732a3430b9b4dab20a6c9508b65e0d8` | committed |
| `evidence/s3/review-r1.md` | 4402 | `2be25415e80793515df3e9ee8eded485f274f700c78a2e59ba2c25bf6117987b` | uncommitted (Reviewer) |
| `evidence/s5a/implementation.md` | 25688 | `af78fef075552ddf2127830bc46cd9a7973bfc745680f058dd368ce776ed91e4` | committed |
| `evidence/s5a/retention.json` | 701 | `ebbd011939219ea0f40b629eee1f273a8f3fa45e5c874ccc4d320e38fa083cbc` | committed |
| `evidence/s5a/review-r1.md` | 4047 | `cb7596a128a52da7dce75f9883ad2f2f0a9f13d07694d0b6c55127d53f752361` | uncommitted (Reviewer) |
| `evidence/s5b/implementation.md` | 27409 | `90ee337e570248c65f9cd0054e8f041e8e2f793dda19e43b940940ac1b8e670b` | committed |
| `evidence/s5b/retention.json` | 841 | `da62d21050a782e9bafc8cacda9cb915f5a51697727e8235c0ba2d03464d2cf4` | committed |
| `evidence/s5b/review-r1.md` | 3979 | `99311a8547d06dd30c4ecffc249ad4e5ab66a7568e6aa294c8412ad6ad2b1ab5` | uncommitted (Reviewer) |

Копирование проверено: sha256 источника = sha256 назначения; для committed-файлов дополнительно совпало с git-blob на HEAD соответствующей ветки. Расхождений содержимого между worktree и веткой нет.

## 4. Связанные строки карты

| Срез | Required-строк | Привязано (REVIEW) | Осталось PENDING |
|---|---:|---:|---:|
| S1-CONTRACT | 59 (26 inventory + 33 manual) | 59 | 0 |
| S2-SOURCEREADER | 68 (31 inventory + 37 manual) | 68 | 0 |
| S3-BUDGET | 28 (12 inventory + 16 manual) | 27 | 1 |
| S5A-LIFECYCLE | 3 | 3 | 0 |
| S5B-RECOVERY | 5 | 5 | 0 |
| **Итого** | **163** | **162** | **1** |

Всего изменено 163 строки (ровно scope), прочие строки карты не тронуты. В карте 444 evidence-записи, у всех существующих артефактов sha256 совпадает с файлом в репозитории.

**Единственная оставшаяся PENDING: `SC-BUD-PROGRESS`** — «Исследование не останавливается из-за общего счётчика, если задача демонстрирует содержательный прогресс и политика позволяет продолжение». S3 доказывает только часть про политику/счётчик (при OFF счётчики не ограничивают: 10 вызовов при env total=1). Условие «содержательный прогресс → продолжение» реализуется и проверяется в S4-COMPLETION (`tool_loop`/`CheckupService`, no-progress guard). Строка остаётся PENDING до кандидата S4; S3-review-гейт из-за неё возвращает 1 ошибку — это честное отражение, а не дефект привязки.

## 5. Результаты гейтов

| Гейт | Команда (срез) | Exit | Ошибки |
|---|---|---:|---|
| plan | `--stage plan --repo C:\Code\Python\adminbot` | 0 | `errors=0` |
| review | `--stage review --slice S1-CONTRACT --candidate 91516d55` | 0 | `errors=0` (scoped=59) |
| review | `--stage review --slice S2-SOURCEREADER --candidate 91516d55` | 0 | `errors=0` (scoped=68) |
| review | `--stage review --slice S3-BUDGET --candidate 163b8ddd` | 1 | `SC-BUD-PROGRESS: mandatory not ['REVIEW','VERIFIED'] (got PENDING)` (scoped=28) |
| review | `--stage review --slice S5A-LIFECYCLE --candidate 3ff04f3f` | 0 | `errors=0` (scoped=3) |
| review | `--stage review --slice S5B-RECOVERY --candidate a515d09d` | 0 | `errors=0` (scoped=5) |

Выводы: `evidence/gates/plan-after-binding.txt`, `evidence/gates/review-S1-CONTRACT.txt`, `review-S2-SOURCEREADER.txt`, `review-S3-BUDGET.txt`, `review-S5A-LIFECYCLE.txt`, `review-S5B-RECOVERY.txt`, плюс контрольный `review-S1-CONTRACT-candidate-f007da33.txt`.

## 6. Что осталось до релизного поезда

1. **S4-COMPLETION** (`services/tool_loop.py`, `services/checkup_service.py`): семантика завершения, продолжение по существенной проблеме, честный partial на уровне чекапа. Закроет `SC-BUD-PROGRESS` и S4-строки.
2. **S3B-INPUT** после S4: таксономия семи ограничений, сохранение фактов за пределами 12 000 символов и квоты метрик (тот же `checkup_service.py` — сериализовано).
3. **S6-PROMPT** после S3B: effective prompt = сохранённая редакция, addendum, устаревший Betterstack только из активного контура.
4. **S5C-EVENTS**: per-job `WATCHDOG_TAKEOVER`, fingerprint с `kind`, совместимость старых строк (после S5B).
5. **S5D-OBSERVABILITY**: WARN-событие отказа регистрации инцидента, счётчики created/updated/reopened/failed/disabled, reconciliation (после S5C).
6. **S5-WATCHDOG**: join-узел S5A–S5D (сам код не пишет).
7. **S0-PRODDATA / W-12**: production-выборки шести инцидентов остаются `NEEDS_PRODUCTION_DATA` (вход расследования, не блокер).
8. **S8-REVIEW-RELEASE**: один релизный кандидат (train tip), независимое ревью комбинированного diff, deploy-гейт, реальный deployed SHA, immediate canaries, effective config parity, rollback; затем перепривязка всех REVIEW-строк к train-tip и `--stage release`. Только после реальных production-наблюдений строки могут стать `VERIFIED`.

До релизного кандидата `candidate_commit` карты остаётся пустым, `deployed_commit` не выставляется; ни одна строка не объявляется production-подтверждённой.

## 7. S4-COMPLETION (добавлено 2026-11-14, unit `pm-s4-bind`)

| Поле | Значение |
|---|---|
| Код-кандидат / review candidate | `7c1e1afbc3be4098b260a816ff4c6bf5c68d04aa` (ветка HEAD; code `8ccd0730`) |
| База | `bbb3055588364a8f48ce56af94fbf65ec1fc4d09` |
| Ветка / worktree | `sc/corrective-s4`; `…smart-corrective-01-0097aecc4a7a-68195166` |
| Implementation | `evidence/s4/implementation.md` `44044c117b7d52d5dd580d121aebf12468dc45e225adaf69884a243c3d032f33` |
| Review | `evidence/s4/review-r1.md` `3a3e4c995ce6d121b3f5839ee616683629fd3ba8497899b488f3a43809ad90c3` |
| Retention | `evidence/s4/cleanup-retention.json` `9f0d4444f1d0a5facf5eb928fd8c8b64db247decc0d634d65b056b2573cd3c37` |

Артефакты скопированы байт-в-байт из candidate worktree; sha256 источника = sha256 назначения.

### Строки S4

| Показатель | Значение |
|---|---:|
| Required-строк S4-COMPLETION (включая перенесённые `SC-BUD-PROGRESS`/`SC-BUD-PARTIAL`) | 35 |
| Привязано к кандидату `7c1e1afb` (implementation + review) | 35 |
| `REVIEW` | 32 |
| `VERIFIED` (ранее подтверждённые `SC-REP-FAIL`/`SC-REP-STOP`/`SC-REP-ESSENCE`) | 3 |
| Осталось `PENDING` в S4 | 0 |

`SC-BUD-PROGRESS` и `SC-BUD-PARTIAL` перенесены из `S3-BUDGET` в `S4-COMPLETION`, поскольку их недостающая семантика («продолжение по содержательному прогрессу», честный partial чекапа) реализуется и проверяется в S4. Поэтому scope `S3-BUDGET` теперь 26 строк (было 28); историческая таблица §4 выше сохраняет снимок на момент привязки S3.

### Review-вердикт и lineage

Reviewer независимо проверил реализацию, тесты и adversarial-сценарии (11/267/650/301 passed); behavioral verdict — pass. Формальный `Needs Fixes` в `review-r1.md` относился **только** к candidate-lineage gate (491 ошибка при запуске гейта внутри candidate worktree, где нет master-only owner input/plan docs). На master owner input `plans/owner_inputs/2026-11-14-smart-corrective-01.md` (sha `8a0239b3…`) и plan docs присутствуют; review-гейт по тому же кандидату дал `errors=0`. Привязка выполнена на уровне REVIEW; ни одна строка не переведена в VERIFIED.

### Гейты

| Гейт | Команда | Exit | Ошибки |
|---|---|---:|---|
| review | `--stage review --slice S4-COMPLETION --candidate 7c1e1afb --repo C:\Code\Python\adminbot` | 0 | `errors=0` (scoped=35) |
| plan | `--stage plan --repo C:\Code\Python\adminbot` | 0 | `errors=0` |

Выводы: `evidence/gates/review-S4-COMPLETION.txt`, `evidence/gates/plan-after-S4.txt`.

`candidate_commit`/`deployed_commit` карты остаются пустыми; S4 — predeploy binding, не production-подтверждение.

## 8. S5C-EVENTS (добавлено 2026-11-14, unit `pm-s5c-bind`)

| Поле | Значение |
|---|---|
| Код-кандидат / review candidate | `e5cc838f7367be830e05be5394a2eea201321f4f` (ветка HEAD evidence `5d7c4798`) |
| База | `7d0c6b409a786960b1057950f32c4ed24dd7cf0a` |
| Ветка / worktree | `sc/corrective-s5c`; `…smart-corrective-01-0097aecc4a7a-e405b67c` |
| Implementation | `evidence/s5c/implementation.md` `f8f8c0ab20acfa84f4c07284fbd7e1a00fdda0ddb14c75974bbe4f9c9d4b10f4` |
| Review | `evidence/s5c/review-r1.md` `d8fcc22ea84e8c103cad1d85f67dc0bb454a993100fefee96fdcbd3cbe1a3c9d` |
| Retention | `evidence/s5c/retention.json` `90e3891874b5a93185ac0419a3268e0b5f3a1bb558277ed7568a9def0bbc4a8f` |

Артефакты скопированы байт-в-байт из candidate worktree; sha256 источника = sha256 назначения.

### Строки S5C

| Показатель | Значение |
|---|---:|
| Required-строк S5C-EVENTS (`SC-WD-W01`, `SC-WD-W11`) | 2 |
| Привязано к кандидату `e5cc838f` (implementation + review) | 2 |
| `REVIEW` | 2 |
| `VERIFIED` | 0 |
| Осталось `PENDING` в S5C | 0 |

Reviewer отдельно отметил, что исходная формулировка `SC-WD-W01` («ровно одно событие на sweep») конфликтовала с owner §9.2 C и architecture §7.1 (per-job evidence). К моменту привязки текст строки уже согласован с owner/architecture: не более одного события на фактически затронутый job, без повторения идентичного aggregate из-за размера batch, пустой batch — без события. Obligation не ослаблена.

### Review-вердикт

`review-r1.md`: **Approved for implemented S5C-EVENTS scope on exact candidate**. Проверены per-job identity/outcomes, пустой batch, `build_event`/durable `mca_events`, fingerprint `kind+job_id`, два kind → два инцидента, 20-id bound и сохранение исторических строк. Mutation-killed: duplicate emission, empty-batch mutation, fingerprint removal. Прогоны: 13 S5C, 64 combined, 40 consumers, 39 self-diag; единственный pre-existing failure (`test_write_points_go_through_single_writer`) воспроизведён на базе и вне scope. Привязка только на уровне REVIEW; ни одна строка не VERIFIED.

### Гейты

| Гейт | Команда | Exit | Ошибки |
|---|---|---:|---|
| review | `--stage review --slice S5C-EVENTS --candidate e5cc838f --repo C:\Code\Python\adminbot` | 0 | `errors=0` (scoped=2) |
| plan | `--stage plan --repo C:\Code\Python\adminbot` | 0 | `errors=0` |

Выводы: `evidence/gates/review-S5C-EVENTS.txt`, `evidence/gates/plan-after-S5C.txt`.

`candidate_commit`/`deployed_commit` карты остаются пустыми; S5C — predeploy binding, не production-подтверждение.

## 9. S5D-OBSERVABILITY (добавлено 2026-11-14, unit `pm-s5d-bind`)

| Поле | Значение |
|---|---|
| Код-кандидат / review candidate | `4185803c46914a593cdf5ebfa5df5bebd5a2585d` (ветка HEAD evidence `343fdfa2`) |
| База | `5d7c4798aae1e5db93ee88bdf62d66577e6d6010` |
| Ветка / worktree | `sc/corrective-s5d`; `…smart-corrective-01-0097aecc4a7a-e6bece84` |
| Implementation | `evidence/s5d/implementation.md` `64716b66e743a9db2823d3b7e07b5e0fa68b69d936fac0a9871ca951ce0d299f` |
| Review | `evidence/s5d/review-r1.md` `e4d125c04a5b47ac5bce2e2b4e07dbb255c92c3b6d4d4c612b1357c19b4de406` |
| Retention | `evidence/s5d/retention.json` `d393ec3d2c5dccb9de361405c84c445c50315e4402bbf4faa27282449ac56606` |

Артефакты скопированы байт-в-байт из candidate worktree; sha256 источника = sha256 назначения.

### Строки S5D

| Показатель | Значение |
|---|---:|
| Required-строк S5D-OBSERVABILITY | 1 (`SC-WD-W10`) |
| Привязано к кандидату `4185803c` (implementation + review) | 1 |
| `REVIEW` | 1 |
| `VERIFIED` | 0 |
| Осталось `PENDING` в S5D | 0 |

`AC-24` связан через `SC-WD-W10.linked_acceptance = ["AC-24"]`; сама `AC-24` остаётся строкой `S8-REVIEW-RELEASE`/`PENDING` до S8 и не переводится в REVIEW этой привязкой.

### Review-вердикт

`review-r1.md`: **Approved for implemented S5D-OBSERVABILITY scope on exact candidate**. Проверены оба пути отказа регистрации инцидента (raise и `status=failed`), ровно один `open_or_update` без рекурсии, WARN `WATCHDOG_INCIDENT_FAILURE`, bounded-счётчики `created/updated/reopened/failed/disabled`, durable `mca_events`, `WATCHDOG_SWEEP.usage_json` фиксированной формы и сохранение recovery-исхода. Mutation-killed: WARN removal (оба пути), `running_contract.deadline_bounded` removal, recursive `open_or_update`. Прогоны: 6 S5D, 70 combined S5A–S5D, 142 event/supervisor (1 pre-existing census failure), 75 self-diag/cover. Привязка только REVIEW; не VERIFIED.

### Гейты

| Гейт | Команда | Exit | Ошибки |
|---|---|---:|---|
| review | `--stage review --slice S5D-OBSERVABILITY --candidate 4185803c --repo C:\Code\Python\adminbot` | 0 | `errors=0` (scoped=1) |
| plan | `--stage plan --repo C:\Code\Python\adminbot` | 0 | `errors=0` |

Выводы: `evidence/gates/review-S5D-OBSERVABILITY.txt`, `evidence/gates/plan-after-S5D.txt`.

### Состояние S5-цепочки

С привязкой S5D все четыре code-среза watchdog-цепочки — **S5A-LIFECYCLE, S5B-RECOVERY, S5C-EVENTS, S5D-OBSERVABILITY — связаны со своими кандидатами на уровне REVIEW**. Join-узел `S5-WATCHDOG` не пишет код; его закрытие/комбинированное ревью и release остаются S8-REVIEW-RELEASE. Ни одна S5-строка не VERIFIED; production-подтверждение — только после деплоя и реальных наблюдений.

`candidate_commit`/`deployed_commit` карты остаются пустыми; S5D — predeploy binding, не production-подтверждение.

## 10. S3B-INPUT (добавлено 2026-11-14, unit `pm-s3b-bind`)

| Поле | Значение |
|---|---|
| Код-кандидат / review candidate | `1bbe767d3a060e6b8ab56bbd1ccff1b0f4879977` (ветка HEAD evidence `b04dd8f7`) |
| База | `7c1e1afbc3be4098b260a816ff4c6bf5c68d04aa` |
| Ветка / worktree | `sc/corrective-s3b`; `…smart-corrective-01-0097aecc4a7a-21b619c2` |
| Implementation | `evidence/s3b/implementation.md` `04964a005723e058287471d53bc3badd4d603bf175e53b4cbba89f1915855a00` |
| Review | `evidence/s3b/review-r1.md` `53679a7c1c6b677bc5ed2ca89e3e40dacf0a3b9b0ac2e2e2e1cf7b1813262a49` |
| Retention | `evidence/s3b/cleanup-retention.json` `166c3be5b8b9fc379a7e26be942df7861bde3c5cc966ccf346705183e0a1bbc4` |

Артефакты скопированы байт-в-байт из candidate worktree; sha256 источника = sha256 назначения.

### Строки S3B

| Показатель | Значение |
|---|---:|
| Required-строк S3B-INPUT | 25 (`SC-INP-*`) |
| Привязано к кандидату `1bbe767d` (implementation + review) | 25 |
| `REVIEW` | 25 |
| `VERIFIED` | 0 |
| Осталось `PENDING` в S3B | 0 |

### Review-вердикт и гейт

Reviewer: implementation/tests adequate (20/385/650/338/233-9), collector call-site expansion принят как часть S3B, mutation probes не выполнены процедурно (tar/PowerShell), поведенческого дефекта не найдено. **Формальный verdict в артефакте — `Needs Fixes`**, и он обусловлен только candidate-worktree lineage gate (483 ошибки: в worktree отсутствуют master-only owner input/plan docs).

На master owner input `plans/owner_inputs/2026-11-14-smart-corrective-01.md` (sha `8a0239b3…`) и plan docs присутствуют; source-lineage ошибок больше нет. Однако review-гейт по exact candidate возвращает **25 ошибок `missing candidate-bound independent Reviewer approval`**, потому что `Needs Fixes` не входит в допустимые approval-вердикты. Approve не подменялся: записан ровно тот verdict, который есть в артефакте.

| Гейт | Команда | Exit | Ошибки |
|---|---|---:|---|
| review | `--stage review --slice S3B-INPUT --candidate 1bbe767d --repo C:\Code\Python\adminbot` | 1 | `errors=25` (`missing candidate-bound independent Reviewer approval`; scoped=25) |
| plan | `--stage plan --repo C:\Code\Python\adminbot` | 0 | `errors=0` |

Выводы: `evidence/gates/review-S3B-INPUT.txt`, `evidence/gates/plan-after-S3B.txt`.

**Следующее действие:** Reviewer должен переиздать review-артефакт с итоговым `Approved` после подтверждения, что master lineage gate проходит (или явным addendum с approval), после чего PM повторно привяжет review-evidence и review-гейт станет `errors=0`. S3B-строки остаются `REVIEW`, не `VERIFIED`; `candidate_commit`/`deployed_commit` карты пусты.

### R2 approval sync (2026-11-14, unit `pm-s3b-r2`)

Reviewer переиздал approval: `evidence/s3b/review-r1.md` теперь содержит раздел «Re-review r2 (approval after master lineage fix)», итоговый verdict — **Approved for predeploy review of exact candidate** `1bbe767d…`. Новый sha256 артефакта: `adb3189ccf3f1e16fbafe70f45a3bd0ba8d30ecacb433eb9569d3ac503cd958e` (worktree copy совпадает).

| Что синхронизировано | Значение |
|---|---|
| Required-строк S3B с обновлённым review-evidence | 25 (`SC-INP-*`) |
| `verdict` в review-evidence | `Approved` |
| `artifact_sha256` | `adb3189c…` |
| Implementation evidence | не изменялось (digest до/после совпал) |
| Статусы | 25 `REVIEW`; `VERIFIED` — 0 |
| `candidate_commit`/`deployed_commit` карты | пусты |

R2 подтвердил: R1 `Needs Fixes` был только candidate-worktree lineage (483 ошибки), поведенческого блокера нет; master lineage даёт 0, а 25 прежних approval-ошибок были следствием старой привязки. После обновления review-evidence:

| Гейт | Команда | Exit | Ошибки |
|---|---|---:|---|
| review | `--stage review --slice S3B-INPUT --candidate 1bbe767d --repo C:\Code\Python\adminbot` | 0 | `errors=0` (scoped=25) |
| plan | `--stage plan --repo C:\Code\Python\adminbot` | 0 | `errors=0` |

Выводы: `evidence/gates/review-S3B-INPUT.txt` (R2, overwrite), `evidence/gates/plan-after-S3B.txt`. S3B остаётся REVIEW-уровнем; production/final VERIFIED не заявляется.

## 11. S6-PROMPT (добавлено 2026-11-15, unit `pm-s6-bind`)

| Поле | Значение |
|---|---|
| Код-кандидат / review candidate | `5d2eb427c5ebc0efa49012a6c8bc963c7fac0605` (ветка HEAD evidence `717bcc61`) |
| База | `b04dd8f7c0122346034b241c3a8c26fbdf0b0511` |
| Ветка / worktree | `sc/corrective-s6`; `…smart-corrective-01-0097aecc4a7a-e7b064d8` |
| Implementation | `evidence/s6/implementation.md` `5202bab726118e14b90888d9576b9581dd28100e01af48f7048da1b3d3c37e4e` |
| Review | `evidence/s6/review-r1.md` `3bee7545007cd782184acfb903da83cdb181639ebb550d13679ba2e1152ab480` |

Артефакты скопированы байт-в-байт из candidate worktree; sha256 источника = sha256 назначения. Отдельного retention-файла в S6 нет; implementation/review на него не ссылаются.

### Строки S6

| Показатель | Значение |
|---|---:|
| Required-строк S6-PROMPT | 55 (`SC-PRM-*`) |
| Привязано к кандидату `5d2eb427` (implementation + review) | 55 |
| `REVIEW` | 52 |
| `VERIFIED` (ранее подтверждённые investigation-строки `SC-PRM-OWNER`/`VERSION`/`TELEMETRY`) | 3 |
| Осталось `PENDING` в S6 | 0 |

`VERIFIED`-строки не понижались: это investigation-факты на 2.58.200, их evidence сохранено; S6 implementation/review evidence добавлено, но новых VERIFIED нет. Остальные 52 строки переведены `PENDING → REVIEW`.

### AC-15/AC-19

S6-строки, представляющие prompt delivery/preservation, приняты на REVIEW. Сами `AC-15` и `AC-19` остаются строками `S8-REVIEW-RELEASE`/`PENDING` с `live_required=postdeploy`: их live-proof — реальный postdeploy-чекап в чате с сохранённой редакцией владельца и effective telemetry/provenance. В map добавлен `slice_notes["S6-PROMPT"].linked_acceptance = ["AC-15","AC-19"]`; status AC-строк не подменялся на REVIEW/VERIFIED.

### Review-вердикт

`review-r1.md`: **Approved for predeploy review of exact candidate `5d2eb427`**, S6 rows and AC-15/AC-19-mapped obligations at REVIEW only. Проверены chat precedence → global → factory, отсутствие записи сохранённых байт, телеметрия без prompt text, active-vs-historical контур (Betterstack/401 удалены только из active), addendum, один speech layer, seal integrity/`PLAN_NOOP`. 5 независимых мутаций каждая уронила целевой тест; 16 focused + 344/451/264 suites; два pre-existing failure (`prompt_field_audit`, `soul1_registry_completeness`) воспроизведены на базе.

### Гейты

| Гейт | Команда | Exit | Ошибки |
|---|---|---:|---|
| review | `--stage review --slice S6-PROMPT --candidate 5d2eb427 --repo C:\Code\Python\adminbot` | 0 | `errors=0` (scoped=55) |
| plan | `--stage plan --repo C:\Code\Python\adminbot` | 0 | `errors=0` |

Выводы: `evidence/gates/review-S6-PROMPT.txt`, `evidence/gates/plan-after-S6.txt`.

### Состояние corrective

С S6 все code-срезы SMART-CORRECTIVE-01 — S1/S2, S3, S3B, S4, S5A–S5D, S6 — связаны со своими кандидатами на уровне REVIEW. Остаются join-узел `S5-WATCHDOG` и `S8-REVIEW-RELEASE` (единый release train, фактический deployed SHA, production canaries, AC-15/AC-19 live checkup). Ни одна S6-строка не VERIFIED; `candidate_commit`/`deployed_commit` карты пусты.

## 12. Release train rebinding 409f4e8a (добавлено 2026-11-15, unit `pm-train-rebind`)

| Поле | Значение |
|---|---|
| Release train | `release/smart-corrective-01`, tip `409f4e8ae31c9c8fa65ef34bf7c4c3a43c86b8e9` (pre-bump code `051ab76a`, v2.58.201) |
| База | `13884daa32e5cf2a1c05c5c43188ca299f8179f8` (deployed code `0e4a144d`) |
| Map `candidate_commit` | `409f4e8ae31c9c8fa65ef34bf7c4c3a43c86b8e9` |
| Map `deployed_commit` | пусто (до фактического деплоя) |
| `slice_candidate_bindings` | сохранены как история; не перезаписывались |

### Что перепривязано

Все **680** evidence-записей на required-строках (280 строк) переведены на candidate `409f4e8ae31c9c8fa65ef34bf7c4c3a43c86b8e9`; исходный кандидат каждой записи сохранён в `bound_from_candidate`. Остальные поля evidence (ref/observation/artifact_path/artifact_sha256/type/verdict) не менялись. `delivery_evidence` не добавлялся.

### Deploy gate

| Гейт | Команда | Exit | Ошибки |
|---|---|---:|---|
| deploy corrective | `--stage deploy --candidate 409f4e8a --repo C:\Code\Python\adminbot` | 1 | `errors=119` (scoped=384) |
| plan | `--stage plan --repo C:\Code\Python\adminbot` | 0 | `errors=0` |
| deploy parent SMART | `--stage deploy --candidate 0e4a144d` (requirements-map.json) | 0 | `errors=0` (scoped=828) |
| deploy parent FC | `--stage deploy --candidate 0e4a144d` (requirements-map-fc-amendment.json) | 0 | `errors=0` (scoped=705) |

Точная раскладка 119 ошибок (полный список — `evidence/gates/deploy-corrective-409f4e8a-blockers.txt`):

| Категория | Кол-во | Что это |
|---|---:|---|
| `PENDING` rows | 93 | S0-INVESTIGATE 29, S5-WATCHDOG 9 (запреты/разделение), S8-REVIEW-RELEASE 55 (AC-01…AC-24 + S8-процесс/артефакты) |
| Нет candidate-bound Reviewer approval | 12 | S0 production/investigation rows (`SC-REP-BASE`, `SC-REP-GH-UNCONF`, `SC-REP-FOLLOWUP`, `SC-REP-FOLLOW-READ`, `SC-REP-CONSIST`, `SC-INV-MANDATE`, `SC-INV-NOTGUESS`, `SC-INV-COMPARE`, `SC-INV-NOINVENT`, `SC-INV-NOBLOCK`, `SC-INV-EXIST`, `SC-WD-W12`) |
| Нет candidate-bound implementation evidence | 14 | S1 process/contract rows с устаревшим sha документных артефактов (`SC-COR-REJ-02`, `SC-OVL-MAP-01..05`, `SC-COR-IDENT/GOAL/REGISTER`, `SC-OVL-NODUP/NOREWRITE/TRIGGER/NOMEM`, `SC-IMPL-WORKFLOW`) |

Выводы: `evidence/gates/deploy-corrective-409f4e8a.txt`, `evidence/gates/plan-after-rebind-409f4e8a.txt`, `evidence/gates/deploy-parent-smart-0e4a144d.txt`, `evidence/gates/deploy-parent-fc-0e4a144d.txt`, `evidence/gates/deploy-corrective-409f4e8a-blockers.txt`.

**Deploy gate не может быть `errors=0`, пока не закрыты эти 93 PENDING + 26 proof-gap строк.** Это не дефект rebinding: rebinding выполнен (0 ошибок candidate mismatch / отсутствующего bound evidence), но map содержит ещё не привязанные S0/S5-WATCHDOG/S8 обязательства и 26 строк без полного proof-набора. Ни одна строка не переведена в VERIFIED; `deployed_commit` пуст. Следующее действие — отдельное решение Orchestrator: либо привязать S8 к integration review 409f4e8a и закрыть S0/S5-WATCHDOG proofs, либо выпускать только после их binding.

## 13. Deploy-stage appendix binding 409f4e8a (добавлено 2026-11-15, unit `pm-deploy-bind-r2`)

| Поле | Значение |
|---|---|
| Appendix | `evidence/release-train/integration-review.md` `2bb30e65935ff05917adac6a6f7960a80bb07544a9ae3ea482e77e65d6b37b91` |
| Merge log | `evidence/release-train/merge-log-corrective.md` `36bb65c07f55eccc65970b0d289b3fb229e1ada5337fe30c30c4f036b179e50b` (скопирован byte-exact из release-train worktree) |
| Investigation | `investigation/production-runs-and-incidents.md` `47049fa8…4118`; `evidence/binding-production-investigation.md` |
| S5A-D | `evidence/s5a|s5b|s5c|s5d/{implementation.md,review-r1.md}` |
| Deploy candidate | `409f4e8ae31c9c8fa65ef34bf7c4c3a43c86b8e9`; `deployed_commit` пуст |

### Что привязано

| Категория | Кол-во | Результат |
|---|---:|---|
| 14 doc rows (stale sha) | 14 | `artifact_sha256` пересчитан по текущим `requirement-mapping.md`/`plan.md`; candidate 409f4e8a; ref/observation не менялись |
| S0 rows (`S0-INVESTIGATE` + `S0-PRODDATA`, включая 12 без approval) | 41 | `REVIEW`; implementation evidence из investigation report/binding, review evidence из appendix |
| S5-WATCHDOG prohibition/separation | 9 | `REVIEW`; S5A-D implementation + appendix approval |
| S8 process/artifact rows | 29 | `REVIEW`; merge log + integration review + appendix |
| `SC-ART-09/10` + `AC-01…AC-24` | 26 | `READY_FOR_LIVE`, `live_required=true`, `live_when=postdeploy`; `postrelease_wait` и `approved_postrelease_wait` — **побайтно равные объекты из appendix** |

Итоговые статусы required-строк: **355 REVIEW, 26 READY_FOR_LIVE, 3 VERIFIED** (только ранее существовавшие S6 investigation-строки; новых VERIFIED нет). `PENDING` — 0. `delivery_evidence` не добавлялся.

### Гейты

| Гейт | Команда | Exit | Ошибки |
|---|---|---:|---|
| deploy corrective | `--stage deploy --candidate 409f4e8a --repo C:\Code\Python\adminbot` | 0 | `errors=0` (scoped=384) |
| plan | `--stage plan --repo C:\Code\Python\adminbot` | 0 | `errors=0` |
| deploy parent SMART | `--stage deploy --candidate 0e4a144d` (requirements-map.json) | 0 | `errors=0` (scoped=828) |
| deploy parent FC | `--stage deploy --candidate 0e4a144d` (requirements-map-fc-amendment.json) | 0 | `errors=0` (scoped=705) |

Выводы: `evidence/gates/deploy-corrective-409f4e8a-r2.txt`, `evidence/gates/plan-after-deploy-bind-409f4e8a.txt`, `evidence/gates/deploy-parent-smart-0e4a144d-r2.txt`, `evidence/gates/deploy-parent-fc-0e4a144d-r2.txt`.

AC wait copy проверен программно: для всех 26 READY-строк `row.postrelease_wait == review.approved_postrelease_wait == appendix.postrelease_wait`. Deploy gate разрешает только controlled deployment exact SHA; production acceptance и parent DONE не заявляются.

## 14. 2.58.202 guard rebinding 0beed63d (добавлено 2026-11-15, unit `pm-guard-258202`)

| Поле | Значение |
|---|---|
| Release train | `release/smart-corrective-01`, tip `0beed63df8037002ccfaacef019b8ea948d957f6` (2.58.202; merge `f08d4996`, bump `a476818d`) |
| База | `409f4e8ae31c9c8fa65ef34bf7c4c3a43c86b8e9` (2.58.201, deployed) |
| Map `candidate_commit` | `0beed63df8037002ccfaacef019b8ea948d957f6` |
| Map `deployed_commit` | пусто |
| Guard code candidate | `a8b6197fc49142097a3ea14e76d10a0bcec5a1eb` (`sc/corrective-s6-guard`) |

### Rebind

- **954** evidence-записи на **367** required-строках переведены с `409f4e8a` на `0beed63d`.
- `bound_from_candidate` = `409f4e8a`; исходная цепочка сохранена в `bound_from_chain` (slice candidate + `409f4e8a`).
- `slice_candidate_bindings` не перезаписывались; `deploy_stage_appendix` сохраняет исходный candidate 409f4e8a и получает `rebound_to=0beed63d`.
- `delivery_evidence` не добавлялся; `deployed_commit` пуст.

### Guard binding (EVOL-016)

Артефакты скопированы в master `evidence/s6-prompt-guard/`; implementation/cleanup совпали с blobs train tip:

| Файл | sha256 |
|---|---|
| `evidence/s6-prompt-guard/implementation.md` | `5cd877604f671cc50eb03f6594808fb15d5244aa8e11404fc9725d103cde834c` |
| `evidence/s6-prompt-guard/review-r1.md` | `244d1f0766e732a4ab62622adb214890cf80328da3b94561ed6026875773e878` |
| `evidence/s6-prompt-guard/cleanup-retained.json` | `6da8e725836fbc61e8b02c44f0bdf5338ebec4878ac0888451904f1763aff5eb` |

Для всех **55** строк `SC-PRM-*` добавлены дополнительные implementation-evidence (guard implementation/tests) и review-evidence (`verdict=Approved`, ref `EVOL-016 guard review`, candidate `0beed63d`). Статусы S6 не менялись: 52 `REVIEW` + 3 ранее существовавшие `VERIFIED` investigation-строки; новых VERIFIED нет.

### Гейты

| Гейт | Команда | Exit | Ошибки |
|---|---|---:|---|
| deploy corrective | `--stage deploy --candidate 0beed63d --repo C:\Code\Python\adminbot` | 0 | `errors=0` (scoped=384) |
| plan | `--stage plan --repo C:\Code\Python\adminbot` | 0 | `errors=0` |
| deploy parent SMART | `--stage deploy --candidate 0e4a144d` (requirements-map.json) | 0 | `errors=0` (scoped=828) |
| deploy parent FC | `--stage deploy --candidate 0e4a144d` (requirements-map-fc-amendment.json) | 0 | `errors=0` (scoped=705) |

Выводы: `evidence/gates/deploy-corrective-0beed63d.txt`, `evidence/gates/plan-after-guard-0beed63d.txt`, `evidence/gates/deploy-parent-smart-0e4a144d-guard.txt`, `evidence/gates/deploy-parent-fc-0e4a144d-guard.txt`.

Итоговые статусы: **355 REVIEW, 26 READY_FOR_LIVE, 3 VERIFIED** (только ранее существовавшие S6 investigation-строки); `PENDING` — 0. AC wait copy остался точным: 26/26 равны appendix. Guard approval — predeploy only; production `prompt_source=chat` в затронутом чате остаётся postdeploy-проверкой.

## 15. 2.58.203 label + anchor binding (добавлено 2026-11-15, unit `pm-bind-258203`)

| Поле | Значение |
|---|---|
| Release train | `release/smart-corrective-01`, tip `e650f2b854755743f2a750024a1f184d2a802e30` (2.58.203; merge `9b101624` label / `8012ce87` anchor, bump `1bdd8507`) |
| База | `0beed63df8037002ccfaacef019b8ea948d957f6` (2.58.202, deployed) |
| Map `candidate_commit` | `e650f2b854755743f2a750024a1f184d2a802e30` |
| Map `deployed_commit` | пусто (до фактического деплоя) |
| Label candidate | `sc/corrective-checkup-label`: код `1a945ec5b5c47ff18d30c5782ee91e63a5e23441`, HEAD evidence `fd2b4bb017d27f101c76fa02b412f7764153226d`, worktree `…-c1b9af67` |
| Anchor candidate | `sc/fc-anchor`: код `b0f6ec79f8693d17d6a9e7b9d18e93612a10dd27`, HEAD evidence `4852c67c7fc82fad39a832059c17122e3828861b`, worktree `…-cfc5172f` |

### Скопированные артефакты (байт-в-байт) и sha256

| Путь в master | Байт | sha256 | Сверка с поездом |
|---|---:|---|---|
| `evidence/checkup-label/implementation.md` | 15906 | `6e7a1676ca9be922b6bdf23c9ee0d62491aae7fd8fa65c2b169d3a0bd85c659a` | blob `6b18a26a` = worktree `fd2b4bb0` = `e650f2b8` |
| `evidence/checkup-label/review-r1.md` | 2460 | `9aa50b38546c5c008b2be2a5587ee968ed460134d0702eaaa54c565b16c8d8dc` | uncommitted (Reviewer); sha256 источника = назначения |
| `evidence/fc-anchor/implementation.md` | 17161 | `20d0c43863cdc94465942ee24413562b128fb3ae8e901491e5527c7b99348828` | blob `4cf546c2` = worktree `4852c67c` = `e650f2b8` |
| `evidence/fc-anchor/review-r1.md` | 4203 | `85a11f54a91df191bcd276c347283a8b16ac432e90ffed5e83238681b67b1607` | uncommitted (Reviewer); sha256 источника = назначения |
| `evidence/fc-anchor/probe_before_after.py` | 4739 | `b107a232fd88434de72c7186099dce0c2e596e38046b43a375d0bd83d24d555d` | blob `d6245883` = worktree = `e650f2b8` |
| `evidence/fc-anchor/mutation_no_anchor_plugin.py` | 857 | `1e8e28fbce44da137893269b4798a73b0f9171a5fec154f7d99b9c1c3eae170f` | blob `2b2ad3a3` = worktree = `e650f2b8` |
| `evidence/fc-anchor/cleanup_retained.json` | 741 | `dc5a06943b9dc386b94f070934cd48180e1fa16bc3bbc13c52d75c0e814580f4` | blob `af12c7de` = worktree = `e650f2b8` |

Anchor evidence лежит в origin-каталоге `plans/features/smart-execution-reliability-01/evidence/fc-anchor/`;
в master он скопирован под `plans/features/smart-corrective-01/evidence/fc-anchor/` (write scope этого юнита),
происхождение и коммиты записаны в каждом evidence-entry (`ref` + `bound_from_candidate`).

### Rebind

- **1064** evidence-записи на **384** required-строках переведены `0beed63d → e650f2b8`; исходный кандидат — в `bound_from_candidate`, цепочка дополнена `0beed63d` в `bound_from_chain` (110 записей были без цепочки, у них она создана).
- Всего в карте теперь **1174** evidence-записи, все с `candidate_commit = e650f2b8`; артефакты существуют, sha256 сходятся (проверка по всем записям, 0 расхождений).
- `slice_candidate_bindings` сохранены как история; `guard_binding.s6-prompt-guard.candidate_commit` переведён на `e650f2b8` с `bound_from_candidate=0beed63d`; `deploy_stage_appendix` — `sha256` обновлён, `rebound_to=e650f2b8`.
- `deployed_commit` пуст; статусы не менялись: **355 REVIEW, 26 READY_FOR_LIVE, 3 VERIFIED (pre-existing), 0 PENDING**.

### Клирикальная правка устаревших pins (не ослабление evidence)

Две записи карты указывали sha256 на версии документов, изменённые **после** привязки 0beed63d (сам факт — дрейф, не новый дефект):

| Артефакт | Было в карте | Стало | Причина дрейфа |
|---|---|---|---|
| `evidence/release-train/integration-review.md` (136 записей) | `2bb30e6593…` | `5299bfc616a30d1940bff7195fb477e85ecd2df9a6b2f0b9901bfecedf6df152` | после привязки в файл добавлены разделы «Delta integration review 2.58.202» и «…2.58.203» (Reviewer, uncommitted на момент привязки) |
| `requirement-mapping.md` (21 запись) | `a5e12a1f04…` | `2ff0d1a2f91d674d55bc9f4b8fa4adb59ecb2dc2d534899030e5279666abe4df` | коммит `81d4dcfd` согласовал текст S5C с per-job контрактом владельца |

Смысл approvals не менялся: appendix по-прежнему содержит «Approved for controlled deployment» для `0beed63d` и добавляет новый (независимый) вердикт по `e650f2b8`. Pin зафиксирован по фактическому содержимому файла на 2026-11-15T06:06:31+12:00; если appendix будет дополнен, pin нужно обновить до следующего гейта.

**Важное ограничение pin:** на момент привязки дополнения appendix (разделы delta-review `2.58.202`/`2.58.203`) были в рабочем дереве master, но ещё не закоммичены их автором (Reviewer/Orchestrator). Поэтому коммит привязки содержит pin на содержимое рабочего дерева; в чистом checkout до коммита appendix гейт по этим 136 записям даст sha-расхождение. После коммита appendix (или любого его дополнения) pin нужно пересчитать до следующего гейта — содержимое при этом должно оставаться содержащим approval `0beed63d` и вердикт по `e650f2b8`.

### Привязка label evidence (S6-ACTIVATION)

Для всех **55** строк `SC-PRM-*` добавлены две дополнительные записи (`candidate_commit = e650f2b8`, `bound_from_candidate = 1a945ec5`):

- implementation (`type: test`) → `evidence/checkup-label/implementation.md` `6e7a1676…`;
- review (`type: review`, `reviewer_role: Reviewer`, `verdict: Approved`) → `evidence/checkup-label/review-r1.md` `9aa50b38…`.

Статусы S6 не менялись: 52 `REVIEW` + 3 ранее существовавшие `VERIFIED` investigation-строки; новых `VERIFIED` нет. Postdeploy-исходы (активация в реальном процессе бота, `factory_revision_applied`, чекап без override с фабрикой 3 462/`3140bb36`, `factory_superseded_manual` в затронутом чате с неизменным sha) остаются `UNVERIFIED`.

### Привязка anchor evidence (SFC-12-09, родительская карта FC)

Для всех **14** строк `req_id=SFC-12-09` в `requirements-map-fc-amendment.json` добавлены две записи (`candidate_commit = e650f2b8`, `bound_from_candidate = b0f6ec79`): implementation/probe (`type: test`) → `evidence/fc-anchor/implementation.md` `20d0c438…`, review (`Approved`) → `evidence/fc-anchor/review-r1.md` `85a11f54…`.

- Статусы не менялись: 14 × `READY_FOR_LIVE`; `live_required=true`, `live_when=postdeploy` и `postrelease_wait` не тронуты.
- `approved_postrelease_wait` к anchor-review **не** приписан: отсрочку approves appendix, а не этот review. Поэтому карта FC здесь **не** перепривязана (остаётся `0e4a144d`); перепривязка FC к 2.58.203 и копирование wait-объектов — отдельный шаг на момент деплоя.
- Production-доказательство SFC-12-09 (чистый изолированный `original_production_scenario` на выкаченном 2.58.203 и live-метрики) остаётся `UNVERIFIED`; итоговый финальный кандидат строк — выкаченный 2.58.203.

### Гейты

| Гейт | Команда | Exit | Ошибки |
|---|---|---:|---|
| deploy corrective | `--stage deploy --candidate e650f2b8 --repo C:\Code\Python\adminbot` | 0 | `errors=0` (scoped=384) |
| plan | `--stage plan --repo C:\Code\Python\adminbot` | 0 | `errors=0` |
| deploy parent SMART | `--stage deploy --candidate 0e4a144d` (requirements-map.json) | 0 | `errors=0` (scoped=828) |
| deploy parent FC | `--stage deploy --candidate 0e4a144d` (requirements-map-fc-amendment.json) | 0 | `errors=0` (scoped=705) |

Выводы: `evidence/gates/deploy-corrective-e650f2b8.txt`, `evidence/gates/plan-after-258203-bind.txt`,
`evidence/gates/deploy-parent-smart-0e4a144d-258203.txt`, `evidence/gates/deploy-parent-fc-0e4a144d-258203.txt`.

### Открытый блокер деплоя (не скрыт гейтом)

Независимый delta-review поезда `e650f2b8` (`integration-review.md`, раздел «Delta integration review 2.58.203») вернул **Needs Fixes**:
на точном поезде `tests/test_p0_prompts_core.py::test_pr01_saved_and_effective_match_registered_revision`
падает с `eff.source=default`, `withheld=true`, `reason=provenance_missing` (stored_sha `3140bb364044`, stored_chars 3462)
вместо `source=global`/`withheld=false` (focused label suite 36 passed / 1 failed). Владелец исправления — Builder
(узкая поправка provenance/effective_prompt под новую метку), затем Reviewer перепрогоняет focused label+anchor suite.

Запись зафиксирована в карте: `deploy_blocker` (candidate, source, sha256 appendix, finding, owner, effect, recheck).
**`deploy gate errors=0` для `e650f2b8` — это структурная привязка evidence, а не разрешение на выкат.**
Выкат 2.58.203 допустим только после устранения дефекта, повторного ревью исправленного поезда и перепривязки карты к новому tip.

## 15. Final 2.58.203 rebind c97c06e4 (добавлено 2026-11-15, unit `pm-final-258203`)

| Поле | Значение |
|---|---|
| Final train tip | `c97c06e45cdbbf45b4c9df500e11cdb1d0486ae5` (2.58.203; merge `a73ddc7f`) |
| База / previous binding | `e650f2b854755743f2a750024a1f184d2a802e30` (2.58.203 pre-fix) |
| Map `candidate_commit` | `c97c06e45cdbbf45b4c9df500e11cdb1d0486ae5` |
| Map `deployed_commit` | пусто |
| Appendix | `evidence/release-train/integration-review.md` `11a12ab5a197d27ff44cf9b6fc6fd2626bc6dc9591e921cedcd8a292f26bad68` |

### Rebind

- **1174** evidence-записи на **367** required-строках переведены с `e650f2b8` на `c97c06e4`.
- `bound_from_candidate = e650f2b8`; цепочка `bound_from_chain` расширена и сохраняет slice candidate → `409f4e8a` → `0beed63d` → `e650f2b8`.
- `slice_candidate_bindings` не перезаписывались; guard binding S6 не менялся.
- `deploy_stage_appendix.sha256` обновлён на `11a12ab5…`; `rebound_to`/`delta_approved_candidate = c97c06e4`.
- Все **136** evidence-записей, ссылающихся на `integration-review.md`, получили `artifact_sha256=11a12ab5…`.
- `deploy_blocker` очищен (`null`), старый blocker сохранён в `deploy_blocker_history`; добавлен `deploy_blocker_resolution`:
  - verdict `Approved for controlled deployment`;
  - reference `evidence/release-train/integration-review.md §Delta review 2.58.203 correction (test isolation)`;
  - source sha `11a12ab5…`.
- `deployed_commit` пуст; `delivery_evidence` не добавлялся.

### Гейты

| Гейт | Команда | Exit | Ошибки |
|---|---|---:|---|
| deploy corrective | `--stage deploy --candidate c97c06e4 --repo C:\Code\Python\adminbot` | 0 | `errors=0` (scoped=384) |
| plan | `--stage plan --repo C:\Code\Python\adminbot` | 0 | `errors=0` |
| deploy parent SMART | `--stage deploy --candidate 0e4a144d` (requirements-map.json) | 0 | `errors=0` (scoped=828) |
| deploy parent FC | `--stage deploy --candidate 0e4a144d` (requirements-map-fc-amendment.json) | 0 | `errors=0` (scoped=705) |

Выводы: `evidence/gates/deploy-corrective-c97c06e4.txt`, `evidence/gates/plan-after-final-c97c06e4.txt`, `evidence/gates/deploy-parent-smart-0e4a144d-final.txt`, `evidence/gates/deploy-parent-fc-0e4a144d-final.txt`.

Итоговые статусы: **355 REVIEW, 26 READY_FOR_LIVE, 3 VERIFIED** (только ранее существовавшие S6 investigation-строки); `PENDING` — 0; новых VERIFIED нет. 2.58.203 delta — test/evidence-only, runtime не менялся; appendix approval разрешает controlled deployment exact `c97c06e4`, production acceptance остаётся postdeploy.

## 16. Production evidence 2.58.203 (добавлено 2026-11-15, unit `pm-prod-bind-258203`)

| Поле | Значение |
|---|---|
| Deployed | `c97c06e45cdbbf45b4c9df500e11cdb1d0486ae5` / 2.58.203 |
| Evidence root | `release-evidence/2.58.203/` (`deploy.md`, `prompt-release.md`, `provenance.txt`, `watchdog.md`, `effective-config.txt`, `fc-canary.md`) |
| Rollback target | `0beed63d` / 2.58.202, не исполнялся |

### 16.1 Corrective map

| Категория | Кол-во | Результат |
|---|---:|---|
| Engineering REVIEW-строки, подтверждённые deployed exact candidate + существующим candidate-bound implementation/review evidence | 355 | `VERIFIED` |
| Production-proven live rows | 4 | `VERIFIED`: `SC-ART-09` (prompt/budget effective state), `SC-ART-10` (deploy/health/identity/rollback), `AC-19` (manual revision pre==post), `AC-20` (real takeover recovered) |
| Future observations | 22 | остаются `READY_FOR_LIVE` с уже одобренными waits |

`AC-15` получил production evidence (`provenance.txt`/`prompt-release.md`): на bot-like штатном resolver сохранённая редакция доставляется (`chat`, 12 469/31d17506, withheld=false), чат без override получает global 3 462/3140bb36. **Реального Telegram-чекапа не было**, поэтому `AC-15` оставлен `READY_FOR_LIVE`, не VERIFIED.

Итог corrective: **362 VERIFIED, 22 READY_FOR_LIVE, 0 PENDING**. `deployed_commit=c97c06e4`; `delivery_evidence` добавлен (deploy/health). Release gate: `errors=22` (ожидаемо, ровно deferred live rows). Delivery gate: **`engineering_delivery=PASS`, `acceptance=PENDING_FUTURE_EVIDENCE`, errors=0**.

Остались: `AC-01…AC-18`, `AC-21…AC-24` — реальные checkup/жанр/смешанное состояние/полнота/инцидентные сценарии, которых не было в живом Telegram-прогоне; waits не менялись.

### 16.2 FC amendment map

- **14** строк `SFC-12-09` → `VERIFIED` по чистому cap-40 `original_production_scenario` (observed/production, 16/40, все 11 предикатов true). Orchestrator decision записан: cap-40 admissible; cap-20 run — `not_observed/unavailable`, не PASS и не failure.
- Остальные FC live rows не расширены: `SFC-12-07` (сценарии A–J), `SFC-13-03` (метрики причин), `SFC-14-03` (широкий process/smoke contract), `SFC-5-10` (FC budget values) остаются `READY_FOR_LIVE`.
- Итог FC: **660 VERIFIED, 45 READY_FOR_LIVE**. Release gate: `errors=45`; delivery gate: `PASS/PENDING_FUTURE_EVIDENCE`, errors=0.

### 16.3 Parent SMART (assessment only; parent map вне write scope)

Parent map не редактировался. Итог: **762 VERIFIED, 66 READY_FOR_LIVE**; release gate `errors=66`, delivery gate `PASS/PENDING_FUTURE_EVIDENCE`, errors=0.

| Row | Assessment |
|---|---|
| `SXR-A1-04` | Effective config 2.58.203 доказывает budgets OFF/caps 0/capacity 1,048,576; runtime SMART не менялся — контракт доказуем, но parent map вне write scope, оставлен READY |
| `SXR-L1-01` | То же: master OFF, скрытого enforcement нет; доказуем, parent map не редактировался |
| `SXR-L2-01` | Нет реального payload/checkup evidence на 2.58.203 — остаётся READY |
| `SXR-L4-01` | Нет реального read-only запроса по собственному коду — остаётся READY |
| `SXR-L6-01` | Нет многошагового source-failure сценария — остаётся READY |
| `SXR-L7-01` | Нет реального Telegram-чекапа — остаётся READY |
| `SXR-L8-01` | Причины I1–I6 не перепроверены на 2.58.203 — остаётся READY |

### 16.4 Гейты

| Гейт | Результат | Файл |
|---|---|---|
| corrective release | `errors=22`, exit 1 (deferred live rows) | `evidence/gates/release-corrective-c97c06e4.txt` |
| corrective delivery | `errors=0`, `engineering_delivery=PASS`, `PENDING_FUTURE_EVIDENCE` | `evidence/gates/delivery-corrective-c97c06e4.txt` |
| FC release | `errors=45` | `evidence/gates/release-parent-fc-0e4a144d-258203.txt` |
| FC delivery | `errors=0`, `PASS/PENDING_FUTURE_EVIDENCE` | `evidence/gates/delivery-parent-fc-0e4a144d-258203.txt` |
| parent SMART release | `errors=66` | `evidence/gates/release-parent-smart-0e4a144d-258203.txt` |
| parent SMART delivery | `errors=0`, `PASS/PENDING_FUTURE_EVIDENCE` | `evidence/gates/delivery-parent-smart-0e4a144d-258203.txt` |

Corrective **engineering delivered**, но не final DONE: 22 live observations остаются. Parent не closable: 66 READY.
