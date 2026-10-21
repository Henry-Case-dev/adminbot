# LEDGER-CFG-TAIL — биндинг хвостовых строк CFG к существующим доказательствам

- **Лейн:** LEDGER-CFG-TAIL (writer, только ledger). Дата: 21.10.2026. HEAD: `e0c11306`.
- **Нового кода НЕТ.** Все evidence существующие; каждая привязка сверена чтением файла и
  фактическим sha256 артефакта (записан в карте). SHA коммитов — реальные объекты Git.
- **Итог:** 23 строки слайсов CFG-07B/CFG-07C: **22 VERIFIED + 1 честный PENDING (CFG-07D.6)**.
  CFG-06: 4 канарейки 06E.4/06F.1/06G.1/06G.4 **уже VERIFIED** (закрыты лейном CFG-06-CANARY,
  коммит `cc7ac8d7`, evidence `evidence/cfg-06/canary/*` @ deployed 7142ffcf) — изменений не
  требуют; CFG-06G.8 — корректный owner_optional (не тронут).

## 0. Алиас-биндинг на candidate-срез карты (конвенция dd6acf83)

candidate_commit карты = `d860a529` (срез волны 07D.5; задеплоен в составе 2.58.104 =
`8ea6ed4e` = d860a529 + runtime-core 04593c8f + bump). Все первичные кандидаты привязанных
строк — его предки (`1b23d4c9`, `7c3a1350`, `f1e31d27`, `8cd2ca14`, `ce77b2c4` — проверено
`git merge-base --is-ancestor`). Поэтому каждая строка несёт один алиас-элемент
@`d860a529` (артефакт — этот файл; для live-строк — release-104/deploy.json) с честной
ссылкой на первичного кандидата; первичные элементы evidence сохранены как есть.

Примечание о канонах: тексты инструкций occasional/frequent после G0 ещё раз уточнены
владельцем (ADD-SAMPLES-UX `29b91004`, «F3 replaced, pins updated», деплой схемы v37 с
2.58.100) — та же владельческая цепочка «точные тексты владельца байт-в-байт», пины
обновлены; наблюдения ниже описывают первичные артефакты на их кандидатах.

## 1. CFG-07B (12 строк) — слайс поглощён UNIFIED-CORE

Первичный вердикт G0: `evidence/cfg-07b-reused/README.md` + `summary.json` (коммит `29cc49ba`,
кандидат v2 `1b23d4c9` = UNIFIED-CORE, прод 2.58.98): REUSED 9 + офлайн 1 + PARTIAL 1, OPEN 0.

| Строка | Статус | Evidence (сокр.) | Комментарий |
|---|---|---|---|
| CFG-07B.F | VERIFIED | unified-core README; cfg-07b-reused README; review-add-exp | Один Core/один helper; второго Character Core/параметра нет (grep MAT_ENABLED = 0) |
| ADD-1.C4 | VERIFIED | cfg-07b-reused; trace-per-chat-off; review-07cg-tail | Грубая манера = Core+Expression; при OFF цитаты «как есть» (шапка F3 байт-пиннута) |
| CFG-07B.1 | VERIFIED | cfg-07b-reused (UI-путь, factory ON); review-add-exp (EXP-UI.*); release-25898; review-accept-96 | Переключатель = «Выражение» (решение владельца F3 20.10); UI в проде с 2.58.98; live-глаза владельца — опционально |
| CFG-07B.2 | VERIFIED | cfg-07b-reused; test_add_exp_expression; design-add-exp §1.4; unified-core README | Одно effective-правило, closed-set + read-alias, миграционная лестница целы |
| CFG-07B.3 | VERIFIED | cfg-07b-reused (F3 байт-канон); EXPR-тесты; off-трасса; 07cg-dictionary | ON — дословный канон владельца; OFF — 0 нового мата, цитаты/URL дословно |
| CFG-07B.4 | VERIFIED | design-add-exp §1.4; cfg-07b-reused; EXPR-тесты | 3 уровня off/occasional/frequent по решению владельца F3 — без оверинженеринга, без «мата в каждую фразу» |
| CFG-07B.5 | VERIFIED | unified-core README §4; route-coverage; review-07cg-tail | Внутренние процессы нейтральны, машинные JSON/конверты целы; применено к Direct/Initiative/Factcheck/Summary/tool |
| CFG-07B.6 | VERIFIED | trace-per-chat-off; test_hot_apply; review-accept-96 (live A/B); EXPR read-alias | Override/hot/без рестарта/fallback — трассы + live 2.58.96 |
| CFG-07B.7 | VERIFIED | cfg-07b-reused §Остатки п.2; directives-fix eval.json; 07d5-summary; test_cfg07_guard_07d5 | Честно: измерение = офлайн-eval (мехсчётчики отменены владельцем 20.10); bounded retry доставлен в 07D.5 (метатекст-триггер, ≤2/≤1); детектор именно стерильности мата отсутствует — сознательное решение, не регресс |
| CFG-07B.8 | VERIFIED | cfg-07b-reused (DIAG-классы, emit_expression_diag); review-add-exp (EXP-DIAG.*); 8cd2ca14 телеметрия | Inspector показывает подмешанное правило; applied/exempted — payload+трассы; флаги шва — WARNING+stage_event |
| CFG-07D.3 | VERIFIED | cfg-07b-reused; eval.json; review-accept-96; route-coverage | Инженерно: офлайн-eval + live 2.58.96 (frequent-мат есть / off — 0); живое наблюдение владельца — опционально (owner_live_checks §2) |
| CFG-07D.4 | VERIFIED | 07cg-dictionary; review-07cg-tail; 07d5-summary (bracket-фикс FA-08); G0 PARTIAL-остаток | Span-run закрыт волнами 07C-G/07D.5: word-bounded срезы, факты/числа/ссылки целы, машинные стадии без мата |

## 2. CFG-07C (11 строк) — волны 7c3a1350 / f1e31d27 / 8cd2ca14 / d860a529+04593c8f

Ревью: review-07cg (Approved), review-07cg-tail (Needs Fixes → B1 закрыт 8cd2ca14),
review-07d5 (Needs Fixes → F1–F4 закрыты) → review-07d5-r2 (Approved). Прод: 2.58.103
(deployed `2a3e4fc9`) и 2.58.104 (deployed `8ea6ed4e`).

| Строка | Статус | Evidence (сокр.) | Комментарий |
|---|---|---|---|
| ADD-1.T7 | VERIFIED | unified-core; 07cg-dictionary; review-07cg-tail; 07d5-summary; release-104 | Композит дельты: backstage-запрет + Expression-мат (factory ON) + один egress-guard |
| CFG-07C.F | VERIFIED | 07cg-reuse-audit (07A.F); review-07cg-tail; 07d5-summary; review-07cg | Дополнение на существующих швах; retry в существующем бюджете; параллельного Writer нет |
| CFG-07.B | VERIFIED | review-07cg-tail; 07d5-summary; release-103; release-104; release-103 postdeploy | Блокирующий критерий: все швы + прод-wiring по байтам; телеметрия 0 events — наблюдение продолжается; реальные чаты — только опционально владельцу |
| CFG-07C.1 | VERIFIED | review-07cg-tail (delivery-шов); test_cfg07_guard_07d5; 8cd2ca14 | Guard после Writer/кеш-хита до сериализации; 0 доп. LLM; факты целы |
| CFG-07C.2 | VERIFIED | 07cg-dictionary; review-07cg | 14 семей/42 маркера + JSON/reason_code/HTML/label; 202 POSITIVE — 0 ложных |
| CFG-07C.3 | VERIFIED | 07d5-summary §2; test_cfg07_guard_07d5; review-07d5-r2 | Детерминированный срез + bounded retry; пустых «успехов» нет |
| CFG-07C.4 | VERIFIED | review-07cg-tail; 07cg-dictionary | Enum-честная деградация/честные пулы; fail-soft без фиктивной уверенности |
| CFG-07C.5 | VERIFIED | review-07cg-tail (6 швов + tool_route + short_reply); route-coverage; unified-core | Все публичные каналы покрыты; машинные JSON/логи исключены |
| CFG-07C.6 | VERIFIED | release-103 postdeploy (ce77b2c4); release-103 deploy.json; 8cd2ca14; review-07cg-tail | Wiring подтверждён по прод-байтам 2.58.103; OFF-паритет (0 вызовов guard при OFF); телеметрия 0 events — наблюдение продолжается |
| **CFG-07D.6** | **PENDING** | — | **НЕ ЗАКРЫТО:** скриншот-корпус ДО/ПОСЛЕ с deployed-SHA сверкой в репо отсутствует (`plans/features/cfg/evidence/cfg-07/07c/**` не существует; по cfg-07-build-plan §5 корпус живёт локально из-за приватных фрагментов, правило 06F.1). Недостающее: маскированный дайджест корпуса + привязка к deployed SHA (2.58.104 = 8ea6ed4e) и флагу flags.factcheck_pipeline_v2 |
| CFG-07D.7 | VERIFIED | route-coverage 18; test_direct_chat:1305; unified-core (16 трасс); review-07cg-tail; 07d5-summary | Переходы/дефолты: off/hot/factory/fallback/лестница; Initiative — общий композер + payload-трасса (отдельного runtime-теста нет — зафиксировано честно); «100%» не объявляется |

## 3. CFG-06 — проверка брифа (изменений не требуется)

- 4 RFL-строки по прежним гейт-логам (06E.4/06F.1/06G.1/06G.4) **уже VERIFIED** с привязкой
  canary-эвиденса (`candidate_commit` 7142ffcf, artifact `evidence/cfg-06/canary/README.md`) —
  закрены коммитом `cc7ac8d7` (лейн CFG-06-CANARY, 4/4 PASS на deployed 2.58.99).
- CFG-06G.8 — корректный `verification_tier: owner_optional` (полный набор метаданных:
  owner_policy_ref, owner_optional_reason, engineering_req_ids) — **не тронут**.
- CFG-04D.4 (owner_optional-кандидат из брифа) — строка слайса CFG-04, вне скоупа лейна.
- Оставшиеся RFL слайса CFG-06 (CFG-06.B, CFG-06F.6, CFG-06J.6) брифом не делегированы —
  не тронуты (у каждой собственная постдеплой-семантика в note).

## 4. Гигиена

- Изменены только `plans/features/cfg/requirements-map.json` (status/evidence/note 23 строк)
  и этот файл. Код, tests/, чужие слайсы (CFG-03, CFG-FINAL, CFG-04, CFG-06) — не тронуты.
- Все `artifact_sha256` пересчитаны из фактических файлов на момент биндинга; волна-файлы
  (tests/services) не менялись с `d860a529` (проверено `git log d860a529..HEAD -- <files>` — пусто).
