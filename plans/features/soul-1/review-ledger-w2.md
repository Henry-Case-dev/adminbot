# REVIEW-LEDGER-W2 — независимая сверка леджера окна-2 (коммит `b1cb1396`)

| Поле | Значение |
|---|---|
| Коммит | `b1cb13964d55135be59d302f4884d631a0826e70` (`docs(cfg+soul-1): ledger window-2 — close CFG-01.AC1/AC2 + AMD rows; AMD.8.3 RFL cross-ref P0`, 3 файла, +128/−22) |
| Вердикт | **Approved** |

## 1. Состав и дифф — ровно заявленный, чужих путей нет

`plans/features/cfg/requirements-map.json` (+24/−8) · `plans/features/soul-1/requirements-map-amendment.json` (+84/−14) · `plans/features/soul-1/evidence/verify/rfl-classification-25886.md` (+34). Фильтр по путям вне `plans/features/cfg/**` и `plans/features/soul-1/**` — пуст.

* **cfg:** изменения только в `CFG-01.AC1`/`CFG-01.AC2` — `status → VERIFIED`, добавлена production-запись на `plans/features/soul-1/evidence/agent-checks-window2/probe-run1-raw.txt` (`type=production`, sha256 `06cc4a07…`) + обновлённый `live_note`; row-level `candidate_commit` копий = `0282fe4b` (историческая привязка слайса сохранена).
* **soul-amend:** `SOUL-AMD.5.17/8.6/8.7/8.8/8.9/8.10 → VERIFIED` (production-записи на `probe-run1-raw.txt` `06cc4a07…` и `probe-run2-closing-raw.txt` `e2682a46…`, включая честную оговорку 8.8 про нефорсированный транзиентный сбой и 8.10 про нефорсированную смену провайдера); **`AMD.8.3` — статус RFL сохранён**, добавлен production-эвиденс (S0–S9, `probe-run2-closing-raw.txt`) с cross-ref на `plans/features/p0-save-init-ux/**` слайс **P0A-PERSIST** (цель существует: файл карты + 7 строк слайса) и объяснением остатка «во всех путях» (дефект chat-scope save — код-фикс P0-лейна, не владельческий гейт); **`AMD.8.11` — RFL + note об остатке** (видео `not_configured/media_source_unconfigured` в обоих прогонах — невыполнимо без медиа-источника).
* **rfl-classification:** дифф **только добавления** — §6 «Окно agent-checks-2» со ссылками на `evidence/agent-checks-window2/**` и вердикт `review-agent-checks-window2.md`; §1–§5 не переписаны.

## 2. Счётчики (мой пересчёт)

* cfg: 287 строк / **244 required → VERIFIED 18 / READY_FOR_LIVE 4** (RFL: `CFG-02A.3`, `CFG-02A.4`, `CFG-02A.5`, `CFG-02.AC1`). Историческая сходимость: `CFG-01.6/AC4` закрыты окном-1 (`509aee90`), `CFG-02A.1/02A.2` — `d3db58ad`, `CFG-01.AC1/AC2` — этим коммитом.
* soul-amend: 94 строки / **79 required → VERIFIED 49 / READY_FOR_LIVE 2** (остатки — `SOUL-AMD.8.3`, `SOUL-AMD.8.11`).
* Оба счётчика **совпадают** с заявленными.

## 3. Гейты verbatim (мой прогон)

* cfg `plan` → `stage=plan inventory=246 manual=41 scoped=0 errors=0` **EXIT 0**;
* soul-amend `plan` → `stage=plan inventory=66 manual=28 scoped=0 errors=0` **EXIT 0**;
* `review --slice CFG-02A --candidate 83ecd202…` → `stage=review … scoped=9 errors=0` **EXIT 0**.
* **Rolling-конвенция подтверждена:** топ-левел `candidate_commit` карты = `83ecd202` (последний связанный слайс). `review --slice CFG-01 --candidate 0282fe4b…` → `scoped=13 errors=1`, и единственная ошибка — `candidate mismatch` на топ-левел поле; **row-level копии чисты (13/0)**. Контроль: тот же слайс с `--candidate 83ecd202` даёт 26 row-level ошибок (эвиденс CFG-01 привязан к `0282fe4b`) — т.е. исторические прохождения слайсов фиксируются транскриптами, а релизная стадия пере-якорит `candidate` на финальный релиз-кандидат.

## 4. Артефакт-аудит

40 уникальных пар `artifact_path`+`artifact_sha256` (cfg — 94 записи, soul-amend — 55) → **0 проблем**: все файлы существуют, sha256 совпадают. Отдельно сверены новые окно-2 артефакты: `probe-run1-raw.txt` (`06cc4a07d5ae…`), `probe-run2-closing-raw.txt` (`e2682a46e953…`), `review-agent-checks-window2.md` — на месте, хэши совпадают.

## 5. Инцидент гонки индекса — изолирован

`552021f0` (мой ошибочный коммит, смявший чужие staged-файлы) и `91236b37` (первая пересборка леджера) — **не достижимы ни из одной ветки** (`git branch -a --contains` пуст), присутствуют только в reflog (`HEAD@{4}` / `HEAD@{1}`). Текущая вершина `master` = `b1cb1396` — **ровно 3 файла**, чужих путей нет; в рабочем дереве нет случайных staged/изменённых файлов карт (в status — только несвязанные soul-1 md соседнего лейна).

## Итог

Леджер окна-2 консистентен: состав/дифф точны, счётчики совпали, гейты 0 ошибок, артефакт-аудит чист (40/40), остатки (`CFG-02A.3/.4/.5`, `CFG-02.AC1`, `SOUL-AMD.8.3`, `SOUL-AMD.8.11`) оставлены живыми осознанно и с честными оговорками. **Approved.**
