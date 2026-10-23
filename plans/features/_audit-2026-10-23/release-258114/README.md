# REL-258114 — сборка поезда 2.58.113 → 2.58.114 (23.10.2026)

Лейн `RELEASE-258114`. База — `origin/master` (`eb3abd63`, 2.58.113 + docs-привязки).
Поезд собран в отдельном worktree `C:\Code\Python\adminbot-wt258114` из `origin/master`
черри-пиком **только кода и тестов**; `plans/**` чужих линий не переносились.

## Состав

| Роль | SHA |
|---|---|
| База (`origin/master` = 2.58.113) | `eb3abd63` |
| pre-bump HEAD (фактический, F8-meta) | `667dc434` |
| Bump-коммит 2.58.114 | SHA появляется после коммита; см. `train-commits.txt` |
| Точка отката (2.58.113) | `e4ee54f3` (bump 2.58.113) / прод-базис — `eb3abd63` |

Версия: **2.58.114**. Проц-сет bump: **31 файл / 33 пары** (`bump-verify.txt`),
`SET EQUAL` с bump-сетом 2.58.113 (`delta-vs-113` → `delta-vs-bump113.txt`).

## Поезд (11 коммитов, порядок)

| # | Источник | SHA в поезде | Что |
|---|---|---|---|
| 1 | `f30feb30` | `673d142c` | ASAP3 style phase1: честные hint-лимиты, document-owned limits, dash rule |
| 2 | `f398cb71` | `5ac005ab` | ASAP3 identity: merge aliases by user_id, live per-turn resolver |
| 3 | `bfc12366` | `d8af77c3` | ASAP3 identity rework: имена L1/initiative окна, uid-aware dossier |
| 4 | `02434414` | `92056406` | ASAP3 UI: два независимых hint-лимита + честный двухслойный Inspector |
| 5 | `6c479ad2` | `81cdaa28` | ASAP3 UI fix: частичные лимиты сохраняют наследование, effective state |
| 6 | `804b68b1` | `0d57ec24` | ASAP3 accept: S4–S10 gap-тесты + initiative fail-open для partial DI |
| 7 | `e3d28812` | `45fe1b54` | ASAP2 telemetry: durable needs_clar/clar_target_present в plan_meta |
| 8 | `fb8f2ad6` | `6a86d352` | ASAP2 boundary: честный маркер границы истории в L1/L2 + T20 probe |
| 9 | `258d3fae` | `af7de4e9` | Speech R3: доставка/адресат инициативы, канон-лестница PREV_CLAR + откат |
| 10 | `5d99293a` | `a8d047a7` | Speech R3b: продолжение после уточнения (L1 4.1) + граница истории (L2) |
| 11 | seam | `667dc434` | Интеграционный шов (см. ниже), не отдельная фича |

Не вошли намеренно: `60789cff`, `00b6db34` — вторая (не прошедшая ревью) реализация
EMBED-IDENTITY-GAPS; проверено, что в поезде их нет (`git log --grep` пусто).

## Разрешение конфликтов

- Конфликты были **только** по `plans/**` (modify/delete): при черри-пике каталог
  отбрасывался, поэтому следующий коммит линии «видел» удаление. Резолв механический —
  `plans/**` из поезда исключён целиком (синхронизируется отдельной линией).
- `258d3fae` модифицирует `tests/test_asap_speech_i_matrix.py`, а базовый R2-коммит
  `6b6f8ef7` (тест-файл R2) в поезд не входил → файл в поезде новый, взят полный
  вариант из `258d3fae` (blob `e34fe3451ee5`). Смыслового конфликта нет: R3-файл
  содержит и R2-базу, и R3-правки.
- Смысловых конфликтов «оба меняли один фрагмент» в коде не было.

## Интеграционный шов (коммит 11)

`tests/test_asap_speech_i_matrix.py::test_i07` (R3) конструирует
`DirectChatService.__new__` (partial DI). ASAP3 identity (`bfc12366`) добавил в
инициативный L1-сайт `alias_resolver=self.aliases`, а ASAP3 accept (`804b68b1`)
ввёл явный fail-open `getattr(self, "aliases", None)` только на Writer-сайте →
`AttributeError`. Исправление: тот же fail-open применён к пропущенному L1-сайту
(намерение одобренного коммита, не новая семантика).

Дополнительно (не код): `tests/test_tool_coordinator_round1026.py` bounds-guard
требует санкции для `services/summary_aliases.py` — добавлена запись с NOTE
(ASAP-3 identity, review-identity/r2 Approved), как это делалось во всех
предыдущих релизах.

## ΔDDL

**0.** В диффе `services/ web/ config/ db/ scripts/ tools/` нет `CREATE/ALTER/DROP TABLE`,
`CREATE INDEX` и бампов `user_version`; `_SCHEMA_VERSION_HUMOR_SAMPLES = 37` не менялся
(`ddl-check.txt`). PG — no-op.

## Fingerprint / F8

- `FACTORY_SET_SHA256_12` = **`0163a686c401`**
- `factory_set_fingerprint()` = **`0163a686c401`** (constant == runtime, PASS)

Смена пина относительно 2.58.113 (`24ae494ac422`) — следствие правок канона R3/R3B
(пин обновлён самим коммитом R3b, не руками bump'а).

Frozen UI-ассеты: `tools/soul1_w4_frozen_check.py` → **FROZEN-ASSETS-OK**
(needle-счётчики HEAD == current; сам отчёт перегенерирован в bump-коммите).

## Guards

См. `guards.txt` (таблица PASS/числа + файлы-логи в этом каталоге).
Оболочка: venv `.venv\Scripts\python.exe` (Python 3.12.0, aiogram 3.31.0), node для JS-пинов.

## Ограничения прогона

Полный repository-wide pytest, деплой/рестарт, live/e2e-на-проде и SSH — вне рамок
лейна (≤40 мин, без прода). UI-проверки — локальные `tests/ui_*_e2e.py` на фикстурах.

## Остаточное

- `plans/**` этой линии (карты/evidence фич ASAP-2/ASAP-3/SPEECH) синхронизируются
  отдельной линией; в поезде их нет, кроме bump-обязательных (F8-meta) и evidence
  каталога этого релиза.
- Привязка карт к bump-коммиту 2.58.114 — задача следующего шага (binding), не сборки.
