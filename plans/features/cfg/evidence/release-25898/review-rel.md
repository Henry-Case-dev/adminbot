# REV-REL-25898 — независимое релиз-ревью кандидата 2.58.98 (pre-push)

- Дата: 20.10.2026. Ревьюер: независимый (lane REV-REL-25898, read-only + этот файл).
- Кандидат: `f9e7dd6798858fed483a0366343ce581f41caf8d` (HEAD master) = код-кандидат v2
  `1b23d4c9beb1544169f51781c2c8a45e8797f719` (RECHECK-25898-R1 Approved) + docs `d82ddc8c`
  (4 plans-файла, без кода) + bump `f9e7dd67`.
- Прод-базис: 2.58.97 @ `99f5672c` — подтверждён предок кандидата (merge-base ancestor).

## 1. Бамп байт-дисциплина — PASS (воспроизведено независимо)

- `git show f9e7dd67`: **files=31, pairs=+33/−33**; программная проверка каждой пары строк:
  все 33 пары = только `2.58.97`→`2.58.98` (включая экранированную форму `2\.58\.97` в JS-регэкспах)
  или HEAD-штамп `2428768`→`1b23d4c` (F8-meta). Нарушений: 0.
- SET EQUAL с процедурой 97 (`fcd73a38`): списки 31 файлов идентичны (Compare-Object пуст), профиль строк
  идентичен — подтверждает `delta-vs-97.txt`.
- Candidate v2 неприкосновенен: `1b23d4c9..f9e7dd67` трогает только version-pin строки тестов
  (24 py + 4 js), settings/README/meta; services/handlers/web-логика — 0 файлов. `d82ddc8c` — plans-only.

## 2. F8-meta штамп — корректен

- `1b23d4c` = 7-симв. префикс short(`1b23d4c9`) — сверено `git log --format=%h`.
- Отклонение от 97 (там штамп = родитель bump, CFG-коммит `24287688`) задокументировано в README
  (отклонение #2). Семантика «runtime-код, под которым издан реестр» соблюдена: штамп указывает
  на одобренную кодовую линию v2 — точнее, чем ссылка на docs-коммит. Не блокер.

## 3. Guards — воспроизведено 4 из заявленных (числа совпали)

| Guard | Evidence | Моё воспроизведение |
|---|---|---|
| Offline-агрегат (эквивалент: версия + счёт пар) | EXIT 0, 11/11 | `import config.settings` → APP_VERSION = **2.58.98**, EXIT 0; пары = **33** (байт-чек коммита) |
| F8-каталог `--check` | CHECK OK 579, EXIT 0 | **CHECK OK: 579 == REGISTRY, EXIT 0** |
| JS-syntax sweep | files=106 bad=0 | **files=106, bad=0** (node --check, web/ + tests/js/) |
| delta-vs-97 | SET EQUAL: True | **SET EQUAL: True** (31/31) |

- Дополнительно: sha256_12 трёх ключевых файлов **из коммита** f9e7dd67 совпали с
  `frozen-fingerprint.txt` (settings `d8f56d928859`, README `bb3de3547148`, meta `69c5248d05a5`)
  — guards считались ровно на закоммиченных байтах.
- Состав evidence: README + 11 артефактов — все на месте.

## 4. Связность и откат

- Runtime-дельта prod(99f5672c)→кандидат = UNIFIED-CORE `37097f7c` + R1 `1b23d4c9` (оба Approved) + версия.
- **Откат:** ветка `release/fix-2.58.97` сейчас НЕ существует (локально/на origin) — по
  workflow_state она создаётся на шаге push (`рубеж release/fix-2.58.97=99f5672c → deploy`).
  Обязательный шаг деплоя №2 ниже. Soft-откат — PREV-лестница ADR-1013-3 + kill-switch'и (задокументированы).

## 5. Постдеплой-обязательства — зафиксированы честно

- `EXP-ACCEPT.CRITERION = READY_FOR_LIVE` с честной live_note: F4-матрица на выкаченном 2.58.98
  (off/occasional/frequent, пороги §4); прежний FAILED acceptance-96 сохранён в истории; off-prod
  eval по новым текстам = false (не приукрашено).
- Owner-пункты: `plans/owner_live_checks.md` §2 (ADD-EXP режимы мата) — информационные, не блокер.
- После матрицы DevOps ставит VERIFIED/FAILED и выполняет `--stage release` — до тех пор родитель не DONE.
- Гейт: воспроизведён `check --stage review --slice EXP-ACCEPT --candidate 1b23d4c9` → **EXIT 0**
  (inventory=20, manual=17, scoped=6, errors=0). cfg release rc1 = очередь не завершена (честно, не блокер).

## Замечания (не блокеры)

1. `deployed_commit` в requirements-map = `95d11472` (2.58.96) — устарел (прод уже `99f5672c`).
   Исправится на `--stage release` записью фактического deployed SHA. Гигиена леджера.
2. Рабочее дерево содержит 2 чужих pre-existing plans-правки + untracked scratch — в коммит f9e7dd67
   не вошли (проверено: коммит = ровно 31 файл бампа + 4 файла docs).

## Вердикт

**Approved** — push + deploy разрешены при выполнении шагов:
1) `git push origin master` (f9e7dd67);
2) создать и запушить рубеж отката: `git branch release/fix-2.58.97 99f5672c` + `git push origin release/fix-2.58.97`;
3) штатный деплой 2.58.98 (процедура deploy_commands.txt, дельта-вайтлист prod..f9e7dd67);
4) постдеплой: F4-матрица на 2.58.98 → честно VERIFIED/FAILED → `--stage release --candidate f9e7dd67 --deployed-commit <prod>`.
Родитель остаётся не DONE до постдеплой-доказательств (READY_FOR_LIVE).
