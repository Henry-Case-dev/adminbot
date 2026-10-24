# P0 CANARY BINDING — 2.58.122 (`c128675a`), 24.10.2026

## 1. Что привязано и к какому коду

| поле | значение | чем подтверждено |
|---|---|---|
| `candidate_commit` | `c128675a6a1294c657f13149994b6424b6fae539` | git-объект в репозитории; прод-HEAD до/во время прогонов |
| `deployed_commit` | `c128675a6a1294c657f13149994b6424b6fae539` | `evidence/canary/report.md` §1, `evidence/withheld-postdeploy.md` §1 |
| версия | **2.58.122** | коммит `chore(release-258122)` |

**Сборка 2.58.123 не существует.** Проверено: нет коммита/ветки/тега `2.58.123`,
`git log --all --grep` пуст; worktree `adminbot-wt258119` стоит на `b3bbb94c`
(ветка `release/2.58.119`), в нём нет коммита финального Expression-фикса; прод — 2.58.122.
Финальный код на `master` — `90fc3ad15c95262175576ee35b6df8d27616cba0` (финальный
контракт речи в хвосте system), он **не задеплоен**. Поэтому карта привязана к реально
измеренному/задеплоенному коду `c128675a`, а кандидатский фикс отражён отдельной
evidence-строкой с `candidate_commit=90fc3ad1`. При появлении сборки 2.58.123 нужна
перепривязка `candidate_commit` отдельным шагом, а не подмена SHA в старых записях.

## 2. Закрыто живой канарейкой (VERIFIED)

| req | статус | наблюдение | артефакт |
|---|---|---|---|
| FC-01 | VERIFIED (с оговоркой) | 4 части, `mixed`, честный `temporal=unknown`, 2 URL, оценки не выданы за факты. **Оговорка:** `decision=None` → план v2 не строился, `verdict.parts` структурно пуст (разбор есть в тексте) | `evidence/canary/report.md` §3 |
| FC-02 | VERIFIED | вторичная публикация с другими словами найдена и использована, лексический фильтр не отсёк | §3 |
| FC-03 | VERIFIED | первоисточник недоступен → вторичные публикации дали доказательства | §3 |
| FC-04 | VERIFIED | `tavily` failed → `exa` ok → `tavily` ok, ответ не деградировал | §3 |
| REQ-CORE-FREESPEECH | VERIFIED | rev8 `ead77b2ab509` активна, оба абзаца 1/1 в core и system, патч идемпотентен | §6 + `withheld-postdeploy.md` §4 |
| SP-03 | VERIFIED | Style Policy на выходе: 13 дефисов, 0 тире, `applied=true` | §4 |
| SP-05 | VERIFIED | 0 инструкций про строчную букву в system, нормальная капитализация | §4 |
| PR-03 | VERIFIED | авторская редакция действует после рестарта/миграции, sha/revision не менялись | `withheld-postdeploy.md` §4 |

## 3. Expression — без смягчения

| req | статус | факт |
|---|---|---|
| EX-01 | **FAILED** | живой мат 1/8 (1/4 + 0/4), `model_ignored_instruction`. Схема карты не имеет `PARTIAL`: частичный результат кандидатского v2 (3/6 свободная длина, 1/4 МИКРО) записан в evidence с `candidate_commit=90fc3ad1`, но в прод не выкачен |
| EX-02 | **FAILED** | различия в реальных LLM-пробах не воспроизводятся (1/8) |
| REQ-EX-STABLE-EFFECT | **FAILED** | режим срабатывает случайно, а не как манера речи |
| REQ-EX-PROVE-REAL-PATH | **FAILED** | реальный путь прода не закрыт; локальные пробы v2 — другая сборка |

`REQ-DONE-MAIN-CRITERION` — **PENDING**: FREQUENT не соответствует настройке владельца,
поэтому главный критерий не закрывается до исправления Expression и нового замера.

## 4. Гейты (24.10.2026)

| stage / slice | errors | EXIT |
|---|---|---|
| plan | 0 | **0** |
| review FACTCHECK (42) | 0 | **0** |
| review CORE (50) | 0 | **0** |
| review CHECKUP (58) | 0 | **0** |
| review PROMPTS (37) | 0 | **0** |
| review EXPRESSION (27) | 4 (EX-01/EX-02/STABLE-EFFECT/PROVE-REAL-PATH FAILED) | **1** |
| review ACCEPT (48) | 1 (REQ-DONE-MAIN-CRITERION PENDING) | **1** |
| release (`--candidate` = `--deployed-commit` = `c128675a`) | 20 | **1** |

Release-ошибки: 4 выражения (FAILED), 2 фактчека (`FC-05`, `FC-08` — READY_FOR_LIVE),
`REQ-DONE-MAIN-CRITERION` (PENDING), 3 `REQ-EX-*` (READY_FOR_LIVE) и **9 строк PROMPTS UI**
(`REQ-PR-UI-*`, `REQ-A4-PR-*`) без release-доказательств live.

## 5. Остаток до честного релиза

1. **Builder/Architect-решение по Expression:** на живой модели 1/8; кандидатский хвостовой
   контракт даёт 3/6 и 1/4. Нужно либо принять ограничение (FREQUENT виден на развёрнутых
   репликах), либо менять длину ответа в плане, а не второй регулятор мата. Затем новый
   живой замер и только потом EX-01/EX-02/STABLE-EFFECT/PROVE-REAL-PATH могут быть закрыты.
2. **PROMPTS UI live:** 9 строк требуют фактического UI-доказательства (Inspector
   saved-vs-active) на релизном кандидате.
3. **FC-05/FC-08** — отдельные живым прогоном не закрыты.
4. **2.58.123** не собран: перепривязка `candidate_commit` и release-гейт — после реальной
   сборки и деплоя.
