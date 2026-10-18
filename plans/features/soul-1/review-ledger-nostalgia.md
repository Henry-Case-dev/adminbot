# REVIEW-LEDGER-NOSTALGIA — независимая сверка леджера ностальгии

Проверяемый коммит: `d45194d44212a379281832aac7be8a9613b6c2b0` (1 файл,
`plans/features/p0-save-init-ux/requirements-map-followup.json`, +83/−18).
Режим: read-only; этот коммит — только данный документ.

Биндинг и цепочка:
* `ae9af5161033ee485e0c002471f0191d9d6b4e41` (fix(nostalgia) + evidence) —
  предок `d45194d4` ✔; `4a4d3849` (review-nostalgia-fix.md, Approved) — предок ✔.
* `source_sha256` карты == фактический sha256 `source-p0-followup-2026-10-18.md` ✔.
* Все evidence-записи слайса несут `candidate_commit` = полный
  `ae9af5161033ee485e0c002471f0191d9d6b4e41` ✔.

## 1. Состав/дифф — подтверждён

Изменены ровно 6 строк слайса P0B-NOST (сравнение с `d45194d4^` по JSON):
`P0B-NOST-RESTORE` → **VERIFIED** (2 evidence), `P0B-NOST-ONE-CONTOUR` →
**VERIFIED** (1), `P0B-SEPARATION` → **VERIFIED** (1); `P0B-NOST-DIAG`,
`P0B-NOST-SCEN-A`, `P0B-NOST-SCEN-B` → **READY_FOR_LIVE** (по 1 evidence).
Все три live_note дословно содержат «postdeploy (DevOps/Orchestrator), не
owner-гейт» и конкретные чеки: DIAG — journal `scenario=A`, воронка
sent/причина, `nostalgia_log`, `mca_events nostalgia_run`, per-chat gate
`-1004482340693`; SCEN-A — journal+funnel; SCEN-B — фактическое срабатывание
B/честная причина. Ref-ы: `review-nostalgia-fix.md` (4a4d3849) +
`evidence/nostalgia/**` (ae9af516).

Пины (сверены и с диском, и с блобом в `ae9af516` — 4/4 совпали):
`prod-readonly-2026-10-18.txt` `f72f051c…`, `green-lane-only-2c916f35.txt`
`d72c0b54…`, `system-prompt-on-vs-off.txt` `ae88951e…`,
`tests/test_p0_followup_nostalgia_ab.py` `92c304ae…`.
Содержание (выборочно, читал сам): прод-дамп — `nostalgia_by_status
[('budget_skip',209),('sent',2)]`, все 209 — `gate_nostalgia` второго чата
`-1004482340693`; `year_back_candidates_now 26738`; smart_messages 2 026 184;
hot `memory.nostalgia_enabled=true`, `min_silence=45`, quiet 23–8, cooldown 12ч,
max/day 3. RED-лог — **9 failed/1 passed** (тот же список, что в ревью);
GREEN — lane-only **334 passed**, combined **370 passed**. Я независимо
перезапустил `dump_prompt_artifact.py`: `bytes_equal_legacy_canon: True`,
`OFF byte-parity: True`, ON без legacy-маркеров, `UNCHANGED`/Core/genre = True,
поля делегированного кандидата (`source=nostalgia`, `nostalgia_due`,
`nostalgia:year_back`) — воспроизведено.

## 2. Не тронуто — подтверждено

`items` побайтово идентичны `d45194d4^` (26 строк, все PENDING); P0B-ACCEPT —
6 PENDING, P0B-INIT-ARCH — 3 PENDING (без изменений); top-level
`candidate_commit`/`deployed_commit` не менялись ('' до и после — rolling);
soul-карты в коммит не входят (1 файл).

## 3. Счётчики — пересчитано

41 строка: `VERIFIED=3`, `READY_FOR_LIVE=3`, `PENDING=35` (26 items + 9
additional) — совпадает.

## 4. Гейт — verbatim

`py -3 %USERPROFILE%\.config\opencode\tools\requirements_gate.py check --stage
plan --map plans/features/p0-save-init-ux/requirements-map-followup.json` →
`stage=plan inventory=26 manual=15 scoped=0 errors=0` **EXIT 0** — совпадает
(26/15/0).

## 5. Индекс — чисто

`git show --numstat d45194d4` = 1 файл (83/18); `git diff --cached` пуст
(посторонних staged нет).

## Замечания (не блокирующие, точность прозы)

1. «28 строк» `silence_too_short`: в пине видно 20 строк (~24 ч), README
   пишет «28+ за 30 дн». Субстанция («каждый тик = silence_too_short»,
   кандидаты не достигаются) подтверждена; само число 28 прямо из пина не
   проверяется (в другом артефакте есть строки и за 16.10 — правдоподобно).
   Рекомендация: при следующей правке карты уточнить формулировку до
   «20+ строк в артефакте (30-дневный журнал: 28)».
2. «ON-промпт (3009 симв.)» — фактически 3009/3010 — это размер ВСЕГО
   артефакта; ON-промпт ≈1.25 к симв. Содержание воспроизведено мной, вывод
   не меняется. Рекомендация: формулировать как «артефакт 3009 симв.».
3. Гигиена артефакта: кириллица в `system-prompt-on-vs-off.txt`
   double-encoded (мохибейк при чтении; ASCII grep-checks читаемы). На
   проверку не влияет (пин + независимый перезапуск скрипта), при случае
   перегенерировать с явной кодировкой.

## Вердикт

**Approved.** Леджер-коммит `d45194d4` точен: состав 6 строк, статусы
VERIFIED/RFL соответствуют acceptance (live-требующие строки не завышены),
пины 4/4, гейт 26/15/0 EXIT 0, ничего постороннего не тронуто. Live-строки
остаются за DevOps/Orchestrator (не owner-гейт); замечания §1–3 —
редакционные, блокеров нет.