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
