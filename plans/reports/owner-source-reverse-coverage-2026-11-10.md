# Обратный аудит покрытия owner-источника — 2026-11-10

**Задача:** проверить в обратную сторону, что каждый эпик/раздел владельческого
`plans/current_task.md` имеет зарегистрированную задачу и карту требований (или осознанно
закрыт), и ответить владельцу на вопрос «не потеряна ли какая-то задача».
**Тип артефакта:** read-only проверка plans/ (продуктовый код не менялся,
`plans/progress_scope.json` и `plans/workflow_state.md` не редактировались).
**Исполнитель:** PM-аудит (субагент), 10.11.2026.

---

## 0. Итог одной строкой

**Ни один из 32 разделов владельческого ТЗ не потерян: у всех есть задача и карта
требований, «осиротевших» эпиков — 0.** Реальный дефект другой и он серьёзнее:
**в рабочем чек-ауте лежит устаревшая линия `plans/`, разошедшаяся с линией выката
29.10.2026.** В чек-ауте нет 14 карт требований, которые есть в выкаченной линии
(13 отсутствуют полностью, журнал `evol` есть лишь в усечённом и незакоммиченном виде),
и нет 14 записей реестра задач. Журнал EVOL в чек-ауте усечён в 6,7 раза.
Именно поэтому часть разделов «выглядят» незарегистрированными.

Масштаб расхождения:

| | чек-аут (master, код 2.58.111) | ветка выката `release/2.58.175` (прод) |
|---|---|---|
| записей реестра задач | 35 | 44 |
| owner-входов | 45 | 55 |
| карт требований | 37 (+2 неотслеживаемых) | 48 |
| строк в картах | 4 245 | 7 568 |
| обязательных строк в разрезе 32 разделов | 957 | 2 934 |

Объединение реестров = **49 задач** (5 есть только в чек-ауте, 14 — только в линии выката).
Ни один из двух реестров не является надмножеством другого.

---

## 1. Метод и границы

1. Извлечены все 32 заголовка H1 `plans/current_task.md` (10 748 строк) с диапазонами.
2. Для каждого раздела найдена покрывающая задача реестра и карта требований; строки карты
   отфильтрованы по `source_line` внутри диапазона раздела (для карт, чей источник —
   сам `current_task.md`), либо взяты целиком (для карт с отдельным дословным снимком).
3. Считались только строки с `disposition: required`
   (в `items` **и** в `additional_requirements`).
4. Проверены **обе** линии истории: рабочее дерево и `release/2.58.175`
   (она же `integ/unify-release` — реестры в них побайтно совпадают).
5. Для проверки «уже доставлено, но не записано» использованы: отчёты деплоя в
   `plans/features/**`, evidence-каталоги, номера версий в картах, ветки с реализацией.
6. Ничего не пересчитывалось «на глаз»: числа ниже воспроизводимы скриптами из §9.

Границы: аудит **не** доказывает семантическую полноту карт (это работа Reviewer по
конкретному кандидату) и не проверяет код прода. Проверялась трассировка
«текст владельца → задача → карта → строки → доказательство».

---

## 2. Полная таблица: 32 раздела → задача → карта → вердикт

Колонки «Чек-аут» / «Выкат» — обязательные строки в формате `всего: VERIFIED+PENDING(+READY_FOR_LIVE)`.
«—» = карты или строк в этой линии нет.

| # | строки | раздел источника | задача (id) | карта | чек-аут | выкат | вердикт | доказательство |
|---|---|---|---|---|---|---|---|---|
| 1 | 1–910 | EVOL — Adminbot Evolution | `evol` | `evol/requirements-map.json` | 46: 0V+46P | 46: 39V+2R4L+5P | COVERED_ACTIVE | выкаты 2.58.153/154/155 VERIFIED |
| 2 | 911–1157 | EVOL — доп. корректирующая директива | `evol` | та же | — | 4: 4V | **COVERED_DONE** | строки 911–1157, все V |
| 3 | 1158–1362 | EVOL — Source Code Reader + Когн. карта | `evol` | та же | — | 68: 23V+45P | COVERED_ACTIVE | ветки `feat/evol-src-reader`, `feat/cog-map-s1..s3` |
| 4 | 1363–1432 | ASAP-FC-ADMISSION-01 | `evol` | та же | — | 20: 20V | **COVERED_DONE** | 20/20 V |
| 5 | 1433–1616 | ASAP-VISION-SYNC-01 | `evol` | та же | — | 93: 89V+4P | COVERED_ACTIVE | 96% строк закрыто |
| 6 | 1617–1750 | ASAP-FC-EVIDENCE-STYLE-02 | `evol` | та же | — | 60: 59V+1P | COVERED_ACTIVE | 1 строка открыта |
| 7 | 1751–2007 | ASAP-UI-02 | `evol` | та же | — | 148: 115V+33P | COVERED_ACTIVE | — |
| 8 | 2008–2442 | ASAP-EVIDENCE-ROUTING-01 v3 | `evol` | та же | — | 140: 130V+9P+1R4L | COVERED_ACTIVE | — |
| 9 | 2443–2731 | ASAP-SUMMARY-COVER-INTEGRITY-01 v2.1 | `evol` | та же | — | 113: 110V+3R4L | COVERED_ACTIVE (только live) | 3 строки ждут реального поведения |
| 10 | 2732–2901 | ASAP-FC-VOICE-01 | `asap-fc-voice-01` | `asap-fc-voice-01/…` | нет карты | 93: 37V+56P | COVERED_ACTIVE | отчёты `w1-p0-verbalizer`, `w2-p1-l1-profile`; ветки `feat/fc-voice-p0`, `-p1-l1-profile` |
| 11 | 2902–4029 | ASAP-EVOL-ANTICLICHE-MEMORY-ADMIN-UX | `asap-evol-anticliche-memory-admin-ux` | `asap-evol-anticliche-memory-admin-ux/…` | нет карты | 573: 10V+563P | COVERED_ACTIVE (крупнейший открытый блок) | 7 отчётов `w-ac-*` + `seam-15-4-15-5` |
| 12–16 | 4030–4578 | EPIC-EXPERIENCE… (E + P + H + порядок исполнения) | `epic-experience-learning-performance-help` | `epic-experience-learning-performance-help/…` | 59: 59P | 132: 132P | COVERED_ACTIVE (зарегистрировано, **не начато**) | 0 строк с evidence; `plan.md` + `slice-graph.json` есть |
| 17 | 4579–4707 | HOTFIX-MEME-PUBLICATION-AND-INITIATIVE-UI | `hotfix-meme-publication-initiative-ui` | `hotfix-meme-publication-initiative-ui/…` | нет карты | 60: 22V+1R4L+37P | COVERED_ACTIVE (частично выкачено) | `reports/deploy-2.58.164.md` + честный `not-verified-2.58.164.md` |
| 18 | 4708–5022 | EPIC-CM-VISUAL-01 | `epic-cm-visual-01` | `epic-cm-visual-01/…` | нет карты | 183: 161V+22P | COVERED_ACTIVE | выкаты 2.58.156/158/159; отчёты `cmv-a…e`, `perf`, `nav-fixes`, `residual×3` |
| 19 | 5023–5534 | EVOL-REPLY-CONTEXT-INTEGRITY-01 | `evol-reply-context-integrity-01` **и** `reply-context-integrity-rci` | две карты (`…-01/…` v5 и `evol-reply-context-integrity/…`) | 6: 3V+1REVIEW+2P | 291: 154V+137P | COVERED_ACTIVE (**двойной владелец**) | `reports/rc-v5-deployment-2026-11-04.md` |
| 20 | 5535–5650 | EPIC-PROMPT-VERSIONING-UX-01 | `epic-prompt-versioning-ux-01` | `epic-prompt-versioning-ux-01/…` | нет карты | 58: 58V | **COVERED_DONE** (с оговоркой §5в) | `reports/deploy-2.58.155-reconcile.md`, пакет в 2.58.155 |
| 21 | 5651–6156 | UNIFIED-REPLY | `unified-reply` | `unified-reply/…` | нет карты | 261: 154V+107P | COVERED_ACTIVE | evidence `ur-a…ur-g`, ветки `ur/a-turn-engine`…`ur/g-acceptance` |
| 22–25 | 6157–6435 | PVR-FC-CORRECTIVE-01 (PVR + FC + приёмка) | `pvr-fc-corrective-01` | `pvr-fc-corrective-01/…` | нет карты | 128: 75V+53P | COVERED_ACTIVE (не завершено) | `evidence/pvr-04/*` (5 ширин, e2e), `vpm-pvr-04.md` |
| 26 | 6436–6701 | BEHAVIOR-GATES-SIMPLIFICATION-01 | `behavior-gates-simplification-01` | `behavior-gates-simplification/…` | нет карты | 155: 67V+88P | COVERED_ACTIVE | выкат 2.58.159; evidence `bgs-01…04` |
| 27 | 6702–6945 | REMOVE-LEGACY-REPHRASING v2.0 | `remove-legacy-rephrasing-01` | `remove-legacy-rephrasing/…` | нет карты | 162: 145V+17P | COVERED_ACTIVE | выкаты 2.58.158/159; `evidence/r09-live-proof.md` |
| 28 | 6946–7419 | EPIC-MEMORY-COGNITIVE-02 | `epic-memory-cognitive-02` | `memory-cognitive-02/…` | 147: 17V+2R4L+128P | 146: 25V+1R4L+120P | COVERED_ACTIVE | выкаты 2.58.161–170, 8 evidence-файлов |
| 29 | 7420–8281 | CLEAN FINAL OWNER SPEC: TIME/REPLY/VISION/RBAC/YM/NOST | `EPIC-ADMINBOT-CORRECTIVE-YM-NOST-20261108` | `epic-adminbot-corrective-ym-nost-20261108/…` | 177: 2V+175P | — | COVERED_ACTIVE | карта 419 строк + crosswalk в `plan.md`; MEM-AUDIT `SRC-0792` V |
| 30 | 8282–9483 | VMQ-ONTO-01 | `vmq-onto-01` | `vmq-onto-01/…` | 47: 47P | — | COVERED_ACTIVE | plan + slice-graph + 47 строк |
| 31 | 9484–10015 | SELF-DIAG-01 | `self-diag-01` | `self-diag-01/…` | 190: 35V+6R4L+149P | — | COVERED_ACTIVE | D1 выкачен в 2.58.173, `evidence/d2/*` |
| 32 | 10016–10748 | MOD-ACL-UX-01 | `mod-acl-ux-01` | `mod-acl-ux-01/…` | 285: 64V+221P | — | COVERED_ACTIVE | M2/M4 выкачены 2.58.175, M5L — 2.58.172 |

## 3. Счётчики вердиктов (25 строк таблицы = 32 раздела H1)

| вердикт | строк | разделы |
|---|---|---|
| **COVERED_DONE** | 3 | 2, 4, 20 |
| **COVERED_ACTIVE** | 21 | 1, 3, 5–9, 10, 11, 17, 18, 19, 21, 22–25, 26, 27, 28, 29, 30, 31, 32 |
| **COVERED_ACTIVE, но не начато** | 1 | 12–16 |
| **UNREGISTERED** | **0** | — |
| **RETIRED** | **0** | — |

Дополнительно зарегистрированы задачи без собственного раздела в `current_task.md`
(это нормально — пришли из чата): `meme-pipeline-refactor-01` (116 строк, 84V),
`p0-meme-image-only` (8, 6V), `p0-meme-publication-hotfix`, `goodmorning-quantum-media`
(3 строки, 0V), `smart-module-semantic-routing-p0` (**карты нет**, см. §6).

---

## 4. Главный дефект: две разошедшиеся линии `plans/`

`master` и линия выката разошлись 29.10.2026 (`merge-base 3193b657`). Следствие —
**линейка выката знает про 14 задач, которых нет в рабочем реестре**, и наоборот.

**Есть только в линии выката (14 задач):** `asap-evol-anticliche-memory-admin-ux`,
`asap-fc-voice-01`, `behavior-gates-simplification-01`, `epic-cm-visual-01`,
`epic-experience-learning-performance-help`, `epic-prompt-versioning-ux-01`,
`goodmorning-quantum-media`, `hotfix-meme-publication-initiative-ui`,
`meme-pipeline-refactor-01`, `p0-meme-image-only`, `pvr-fc-corrective-01`,
`remove-legacy-rephrasing-01`, `reply-context-integrity-rci`, `unified-reply`.

**Есть только в рабочем реестре (5 задач):** `EPIC-ADMINBOT-CORRECTIVE-YM-NOST-20261108`,
`mod-acl-ux-01`, `self-diag-01`, `smart-module-semantic-routing-p0`, `vmq-onto-01`.

**Карты, которых нет в чек-ауте (14 файлов):** `asap-evol-anticliche-memory-admin-ux`,
`asap-fc-voice-01`, `behavior-gates-simplification`, `epic-cm-visual-01`,
`epic-prompt-versioning-ux-01`, `evol-reply-context-integrity-01`, `evol`,
`goodmorning-quantum-media`, `hotfix-meme-publication-initiative-ui`,
`meme-pipeline-refactor-01`, `p0-meme-image-only`, `pvr-fc-corrective-01`,
`remove-legacy-rephrasing`, `unified-reply`. Для 13 из них каталога в чек-ауте нет вовсе;
`evol/requirements-map.json` существует, но **усечён**: 304 строки/46 обязательных
против 2 052 строк/640 обязательных в линии выката, и не закоммичен.

**Не закоммичено в чек-ауте (риск потери):**
`plans/features/evol/` целиком (`??`) и
`plans/features/epic-adminbot-corrective-ym-nost-20261108/requirements-map.json` (`??`).
Журнал EVOL — 597 КБ, единственная копия в рабочем дереве усечена; полная версия
существует только как коммит в линии выката.

**Практический смысл:** пока координатор считает прогресс по рабочему
`plans/progress_scope.json`, из знаменателя выпадают 14 задач и ~2 000 обязательных
строк (2 934 в разрезе разделов против 957 в чек-ауте), а разделы 4–9
(ASAP-коррективы фактчека) выглядят «без покрытия», хотя в выкаченной линии по ним
574 обязательные строки, из которых 523 закрыто и 4 ждут live-проверки.

---

## 5. Разбор предварительных находок: что подтвердилось, что опровергнуто

### (a) `EPIC-EXPERIENCE-LEARNING-ADMIN-PERFORMANCE-HELP` — **опровергнуто**

Не «незарегистрированный эпик». Он зарегистрирован в линии выката
(`epic-experience-learning-performance-help`, статус `PENDING`,
`coverage_complete: true`), имеет `plan.md`, `slice-graph.json` и карту на
**176 строк** (не 75; в чек-ауте лежит усечённая копия на 43 строки).
Верно другое: **работы не начато** — 132 обязательные строки, 0 строк с evidence.
Это соответствует прямому указанию владельца в самом разделе: эпик ставится
**после** прежнего содержимого `current_task.md`, а «H. Справка» названа
«ПОСЛЕДНЯЯ ОТДЕЛЬНАЯ ЗАДАЧА». То есть это не потеря, а очередь.

### (b) Построчно по списку — **все опровергнуты как «unregistered/unmapped»**

| раздел | что на самом деле |
|---|---|
| `HOTFIX-MEME-PUBLICATION-AND-INITIATIVE-UI` | задача + карта 60 обязательных (22V+1R4L+37P); выкат 2.58.164 с честным списком непроверенного |
| `UNIFIED-REPLY` | задача + карта 261 (154V+107P), статус BUILDING, evidence ur-a…ur-g |
| `PVR-FC-CORRECTIVE-01` | задача + карта 128 (75V+53P), статус PENDING, 77 файлов в каталоге фичи |
| `REMOVE-LEGACY-REPHRASING` | задача + карта 162 (145V+17P), выкаты 2.58.158/159 |
| `BEHAVIOR-GATES-SIMPLIFICATION-01` | задача + карта 155 (67V+88P), выкат 2.58.159 |
| `EPIC-CM-VISUAL-01` | задача + карта 183 (161V+22P), выкаты 2.58.156/158/159 |
| `EPIC-PROMPT-VERSIONING-UX-01` | задача + карта 58 (58V), пакет выкачен 2.58.155 |
| `ASAP-FC-VOICE-01` | задача + карта 93 (37V+56P) |
| `ASAP-EVOL-ANTICLICHE-MEMORY-ADMIN-UX` | задача + карта 573 (10V+563P) |
| `CLEAN FINAL OWNER SPEC…` | задача + карта 177 (2V+175P), crosswalk в `plan.md` |

Что **подтвердилось** из предварительного списка: ни одна из этих фич **не видна в
рабочем реестре и не имеет карты в чек-ауте**. Как «задача отсутствует в проекте» —
неверно; как «отсутствует в текущем рабочем дереве» — верно и требует починки (§6, п.2).

### (c) «Уже доставлено, но не записано» — **частично подтверждается, с двумя оговорками**

1. **MEMORY (раздел 28).** Работа MEMORY-06/07/08 выкачена (отчёты 2.58.161–170,
   8 evidence-файлов), но в журнале карты привязана лишь часть: в чек-ауте
   17 V из 147, в линии выката 25 V из 146, остальные 120–128 строк `PENDING` без evidence.
   Честный вывод: **часть доставленного не забунжена**, но построчно утверждать «всё
   доставлено» нельзя — нужна ограниченная сверка, а не переобъявление статусов.
2. **PROMPT-VERSIONING (раздел 20).** Задача `VERIFIED`, 58/58 строк V, выкат 2.58.155
   подтверждён. Но в полосе `plans/features/prompt-versioning-ux/reports/pv-s7-review.md`
   записан незакрытый P1: нет durable-доказательства успешного
   `restore_backup`/`rollback` и CAS-409 именно на пути промпта (`PVR-REV-01`,
   «Needs Fixes, узко только тесты», помечен `blocks_parent_done: true`).
   Строки `PVR-REV-01` в карте раздела **нет вообще** — то есть открытый пункт не
   потерян как работа, но отсутствует в журнале требований. Требует решения владельца
   журнала, а не моего переобъявления.
3. Доставка остальных подтверждена версиями: 2.58.150 (мемы только картинкой),
   2.58.152/164 (мем-пакет), 2.58.155 (версии промптов), 2.58.156/158/159
   (когнитивная карта), 2.58.158/159 (RLR, BGS), 2.58.170/172/175 (MOD-ACL).

---

## 6. Что нужно зарегистрировать/починить (без создания новых рабочих единиц)

Раз ни один раздел не потерян, **новых задач создавать не нужно**. Нужны пять
точечных действий; для каждого указан приоритет относительно текущего P0
(`smart-module-semantic-routing-p0` + продолжение MOD-ACL M2/M4A).

| # | действие | id | приоритет | уже частично выкачено? |
|---|---|---|---|---|
| 1 | Создать карту требований и дословный снимок источника для уже зарегистрированной, но **бескартовой** задачи; вход `OI-2026-11-10-SMART-MODULE-SEMANTIC-ROUTING` до сих пор `reconciled: false` | `smart-module-semantic-routing-p0` | **P0 — блокирует**, это ровно тот класс дефекта, который аудит должен ловить: работа идёт, журнала нет | нет |
| 2 | Восстановить линию выката в рабочем дереве: 13 карт + полная версия `evol` (2 052 строки) + 14 записей реестра; закоммитить неотслеживаемые `plans/features/evol/` и карту Nov-8 эпика | 14 существующих id из §4 | **P0 — блокирует честный прогресс** | да (в ветке) |
| 3 | Свести двух владельцев раздела 19 к одному: `evol-reply-context-integrity-01` (v5, 291 строка) и `reply-context-integrity-rci`/`evol-reply-context-integrity` (12 строк) | один из двух id, выбрать существующий | P1 | да |
| 4 | Довести `pvr-fc-corrective-01`: 53 обязательные строки открыты (75 V уже есть, включая PVR-04); на 05–06.11 контракт BGS фиксировал полосу как «не стартовала», сейчас работа начата; владелец велел ставить её **после** UNIFIED-REPLY | `pvr-fc-corrective-01` | P1 (после `unified-reply`) | частично: 75 V, PVR-04 evidence |
| 5 | Ограниченная сверка журнала: MEMORY 120–128 непривязанных строк против отчётов 2.58.161–170; добавить строку под `PVR-REV-01` | `epic-memory-cognitive-02`, `epic-prompt-versioning-ux-01` | P2 (учёт, не работа) | да |

Отдельно, без приоритета-блокера: `epic-experience-learning-performance-help`
(132 строки, 0 evidence) стоит в очереди **последним по прямому указанию владельца** —
его отсутствие в работе не является пропуском; в рабочий реестр его всё равно надо
вернуть (входит в п.2).

---

## 7. Проверка `owner_inputs`

Проверены оба реестра (45 входов в чек-ауте, 55 в линии выката, объединение — 66 id).

* **Входов с несуществующей целевой задачей — 0** (в обеих линиях).
* **Входов с отсутствующим файлом-источником — 0** (в обеих линиях).
* **Дубликатов id задач и входов — 0.**
* **Не reconciled:** ровно один — `OI-2026-11-10-SMART-MODULE-SEMANTIC-ROUTING`
  (см. §6 п.1).
* **11 входов рабочего реестра покрывают обязательства, которых в рабочей карте
  `evol` нет** — `OI-2026-10-31-EVOL-ADDENDUM`, `…EVOL-SRC-COG`,
  `…ASAP-FC-ADMISSION`, `…ASAP-VISION-SYNC` (+`-WATCHDOG`),
  `…ASAP-FC-EVIDENCE-STYLE`, `…NAV-CONTRACT`, `…ASAP-UI-02`,
  `OI-2026-11-01-ASAP-EVIDENCE-ROUTING`, `…SUMMARY-COVER-INTEGRITY`,
  `OI-2026-11-02-PERF-PARITY`. Причина — усечённая карта `evol` (§4), а не потеря
  входов: в линии выката эти обязательства присутствуют (574 строки по разделам 4–9).
* **Файл без записи в реестре:** `plans/owner_inputs/2026-11-10-vector-memory-no-settings.md`
  (жалоба владельца 10.11: «раздел векторной памяти открылся, но настроек в нем нет»).
  Содержательно относится к `mod-acl-ux-01` §5, но как отдельный вход не зарегистрирован —
  это единственный неучтённый owner-вход, который я нашёл.
* **Снимки источников не устарели:** построчная сверка 13 дословных снимков с текущим
  `current_task.md` даёт совпадение 91–100 %; все несовпавшие строки — служебные
  заголовки снимков (путь, SHA, дата), а не обязательства владельца.

---

## 8. Что осталось непроверенным

1. **Семантика строк** внутри карт: соответствует ли каждая строка тексту раздела
   (проверялась только адресация по `source_line`/снимку, не смысл). Это работа
   Reviewer по конкретному кандидату.
2. **Фактическое состояние прода** 2.58.175 по каждому открытому пункту: аудит
   опирался на отчёты деплоя и evidence, а не на живую проверку сервера.
3. **Полоса `prompt-versioning-ux`**: карты у неё нет вовсе (только review-отчёты
   `pv-s0s1…pv-s7` и 154 файла в каталоге) — я не могу утверждать, что 58 строк
   эпик-карты покрывают все пункты полосы; расхождение зафиксировано в §5в.
4. Раздел 19 в линии выката представлен двумя картами с разным объёмом (291 и 12 строк);
   какая из них каноническая — решение координатора (§6 п.3), а не аудита.

---

## 9. Воспроизводимость

Скрипты аудита (временные, вне репозитория, по политике WorkspaceData):
`…/WorkspaceData/runs/c742e4de9e92c489/reverse-coverage-audit-e3c16e4adf97/temp-75cd412fa2/`
— `final_table3.py` (таблица §2), `validate.py` (§7), `branchmaps.py`,
`branchreg.py` (реестры и карты линии выката), `drift2.py` (сверка снимков §7).

Ключевые команды:

```
git merge-base HEAD release/2.58.175          # 3193b657, 29.10.2026 — точка расхождения
git show release/2.58.175:plans/progress_scope.json | jq '.tasks|length'   # 44
py -3 -c "import json;print(len(json.load(open('plans/progress_scope.json'))['tasks']))"  # 35
git ls-tree -r --name-only release/2.58.175 plans/features | grep requirements-map | wc -l  # 48
git ls-files plans/features | grep requirements-map | wc -l                                 # 37
git status --short plans/features/evol        # ?? (не закоммичено)
```
