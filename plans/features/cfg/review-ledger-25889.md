# VERIFY-LEDGER-25889 — вердикт (сверка учётного прохода 2.58.89)

Независимая проверка ledger-коммитов `d3db58ad` (содержательный) и `df13a0b9` (gate-лог). Read-only; этот коммит — только данный документ.

## 1. Состав — ок
- `d3db58ad`: **81 файл** = cfg-карта (M) + soul-amendment (M) + `release-2.58.89-report.md` (A) + **78 файлов** `evidence/release-25889/**` (A); чужих путей нет.
- `df13a0b9`: **1 файл** — `evidence/release-25889/ledger-25889-gates.txt` (79-й файл эвиденса).
- Перенос из ветки релиза: evidence-дерево **byte-identical** (`git rev-parse` tree = `13597aae8d4c…` и там, и на master; 78 файлов). Отчёт — ровно **1 хунк** правки (`(5 файлов)` → `(6 файлов: image_generation, tool_router, worker_budget, app.js, index.html, app.css)`) — это фикс моего incidental-замечания по `soul-byte-equal.txt`; иных правок нет.
- Секрет-скан эвиденса: совпадений 0.

## 2. Карты — пересчитал сам
- cfg: **VERIFIED 14→16, RFL 8→6** (PENDING 265 без изменений); `deployed_commit` `c37b8577`→**`d59fab944bcb3eb0f5d3fa69101d8488da1c155b`** при `candidate=83ecd202…` — dual-line цел.
- CFG-02A-семейство: **V = {.1, .2, .6, .7, .D}, RFL = {.3, .4, .5, .AC1}**. У всех четырёх RFL `live_note` = «postdeploy-**агентский** остаток (**не владельческий**)» с конкретным сценарием. `.1/.2` получили реальный production-эвиденс (`prod-payload-bytes.txt` sha `96aee129…`, `post-check.txt` sha `ff9cd1a7…`, `hashes.txt` sha `2f44e1fa…`), у `.2` f3-оговорка зафиксирована как есть («расход 0» правдив; ссылка на `review-release-25889.md` §4.4).
- soul-amendment: статусы не тронуты (43/43/8); к `SOUL-AMD.6.3` добавлена **production-запись** (candidate `720be161`, `post-prod-bytes-entry-e2e.json`, sha `03229d4f…`, ref на `review-speech-mobile.md` §5.1/§2, «статус строки не меняется»). soul main не тронут; soul `deployed_commit` = `eafbe2e7…` без изменений.

## 3. Девиации docs-only — приемлемы
- (а) отчёт/эвиденс перенесены на master: evidence byte-identical, в отчёте только однострочный фикс 5→6 (по моему вердикту) — ок.
- (б) 3 stale-пина `artifact_sha256` на `review-cfg-02a.md` обновлены (файл дополнялся R3/R4): старый `bb6fd7e3…` больше не встречается (0 вхождений), все 3 записи == текущему sha256 файла `660d6691a0a574…17ca`; статусы не затронуты (пин-правка в строках `.3/.7/.D` без изменения статусов).

## 4. Гейты (мой прогон verbatim) — ок
- cfg plan: `stage=plan inventory=246 manual=41 scoped=0 errors=0` **EXIT 0**
- cfg review `--slice CFG-02A --candidate 83ecd202…`: `stage=review … scoped=9 errors=0` **EXIT 0**
- soul-amend plan: `inventory=66 manual=28 scoped=0 errors=0` **EXIT 0**
- Совпадает с содержимым `ledger-25889-gates.txt`.

## 5. Артефакт-аудит — issues=0
204 записи с `artifact_sha256` (cfg + soul main + soul amendment), **40 уникальных пар путь+sha256 — проверены все** (спот ≥20 перевыполнен): 0 mismatch, 0 missing, конфликтов sha по одному пути нет.

## Замечания
Блокирующих нет. Леджер исполнил рекомендации `review-release-25889.md` §5 точно: закрыты `.1/.2` (с f3-оговоркой), `.3/.4/.5/AC1` оставлены с агентскими live_note, AMD.6.3 получил production-запись, `deployed_commit` обновлён, отчёт поправлен.

## Вердикт
**Approved.**
