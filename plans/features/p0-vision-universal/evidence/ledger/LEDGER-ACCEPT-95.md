# LEDGER-ACCEPT-95 — привязка живой приёмки 2.58.95 к картам

Дата: 2026-10-20 (system local +12:00). Режим: docs-only; прод-код, `workflow_state.md`,
`progress_scope.json` и пользовательский `plans/current_task.md` не менялись.

Основание: `plans/features/p0-vision-universal/review-accept-95.md` (REV-ACCEPT-95,
**Approved**, коммит `112cfcc0`) + `plans/features/p0-vision-universal/evidence/release-25895/acceptance/**`
(60 файлов) + `plans/features/cfg/evidence/cfg-03/acceptance/**` (8 файлов).

Кандидат/деплой: **2.58.95 @ `113f3a629cab54f7fcc261349a7c9af3b90f56d7`**
(T0 2026-10-19 13:07:43Z, MainPID 3716545, NRestarts=0). Карты `cfg` и `p0v` переведены на этот
candidate/deployed; старые evidence-записи сохраняют свои исторические candidate-хеши.

## 1. Закрытые строки (VERIFIED)

| Строка | Что именно закрыто | Evidence (repo-relative) |
|---|---|---|
| **CFG-03.6** | live API: 5 мёртвых ручек, exact-маркер=5, served app.js==disk; live UI: «Память», модалки «Ответы в чате»/«Выжимка видео», console errors 0, mobile 390 без overflow | `plans/features/p0-vision-universal/evidence/release-25895/acceptance/p6b-showcase-api.json`; `plans/features/cfg/evidence/cfg-03/acceptance/ui-live-check95.json`; `…/ui/01-memory-honest-desc-live.png` |
| **CFG-03.4** (live-половина) | 2 горячие ручки без рестарта: `flags.vision_enabled` OFF/ON; `limits.image_daily_limit` — 1 генерация, вторая отклонена до платного вызова, точное восстановление | `…/release-25895/acceptance/p2-vision-off.json`; `…/p4b-generation.json`; `…/runs/accept95b-run.log` (базовые маркеры) |
| **CFG-03.11** (live-спот) | 3 класса негативов без записи: 422 (тип), 422 (select), 409 (stale), значения до==после | `…/release-25895/acceptance/p5b-negatives.json` |
| **CFG-03.12** (live-половина) | OFF: tool+ход честно не выполняются, 0 анализов/джоб; ON: анализ стартует (адаптивный путь), терминальный parse_error честный | `…/p2-vision-off.json`; `…/p3b-vision-adapt.json` |
| **CFG-03.R4** | `manual-checks.md` §1–3: список живых/владельческих проверок с точными сценариями, использован в волне | `plans/features/cfg/evidence/cfg-03/manual-checks.md` |
| **CFG-02B.2 / .2.3 / .8** | live UI ON-предпосылка (burst=2, cooldown=120, per_user), ровно 2 взаимоисключающих режима, факты «Лимиты генерации», mobile 390, OFF-restore | `plans/features/cfg/evidence/cfg-03/acceptance/ui-live-check95.json`; `…/ui/04-images-freq-on-facts-live.png`; `…/ui/06-images-freq-off-restored-live.png` |
| **ADTR-POSTGEN-PENDING** | live pending/deadline_exceeded: 1 provider call, фото доставлено, bounded 20 c, Writer честный, доставка не блокирована; gen2 — 0 вызовов/фото | `…/release-25895/acceptance/p4b-generation.json` |
| **Базовые маркеры** | нет отдельной строки-требования; production-запись добавлена в CFG-03.4 и P0V-PIPE-E2E: healthz 2.58.95, NRestarts=0, SKIPS=0, 402=0, user_version=36, mca errors=0 | `…/runs/accept95b-run.log` + `final95d.json` |

Формулировки ограничения охвата — в `reason`/`note` строк: live-половина 03.4/03.11/03.12 **не**
выдаётся за полный per-параметр/UI-контур. Полная матрица 03.4/03.11 — build-evidence
`review-cfg-03.md` (`f8bb638d`) + `plans/features/cfg/evidence/cfg-03/**`; UI-часть 03.12 —
существующее P0V-UI/e2e evidence.

## 2. Честные остатки (READY_FOR_LIVE / UNVERIFIED)

- **P0V-PIPE-CONTEXT** — остаётся `READY_FOR_LIVE`. Postgen ON дал `pending/deadline_exceeded`
  с пустым `detail`; длинные PNG (1 337 017 B и 1 115 814 B) дали `failed/parse_error`, GT 0/8 и 0/3.
  Буквальный критерий `[vision] postgen | … | detail=…` non-empty и positive half (ready+GT) не
  воспроизведены. Ранее 94 §1: ready-анализ id=5 дошёл до ответа (mid 1166167) — это не отменяет
  текущий остаток.
- **ADTR-POSTGEN-ON** — `READY_FOR_LIVE`: ON-проводка и 1 vision transport call подтверждены live,
  но `ready` не наблюдался (бюджет 20 c < латентность бесплатной модели на 1024×1024).
- **ADTR-POSTGEN-OFF** — `READY_FOR_LIVE`: генерация при Vision OFF в волне 95 не выполнялась;
  OFF-контур — unit/байт-паритет.
- **ADTR-POSTGEN-DEDUP** — `READY_FOR_LIVE`: на gen1 дублей нет (1 фото/1 пост-ответ/1 vision-вызов),
  но cache-hit replay в волне не воспроизводился.
- **content_media** («Медиа-шара») — live-группа не отрендерилась в окне «Выжимка видео»
  (`groups=[]`); статический/e2e маркер PASS. Это остаток 03.1, не 03.6.
- **CFG-02A.3/.4/.5/.AC1** — `N/A (reuse)` для этой волны: статус `READY_FOR_LIVE` сохранён,
  добавлен note «вне волны 95; reuse CFG-02A, live-остаток не перепроверялся».

## 3. Гейты (фактические прогоны)

Полные логи: `plans/features/cfg/evidence/ledger/accept95-gates.txt` и
`plans/features/p0-vision-universal/evidence/ledger/accept95-gates.txt`.

| Прогон | rc | Итог |
|---|---:|---|
| cfg plan | 0 | `inventory=246 manual=41 errors=0` |
| cfg release (`113f3a62`) | 1 | 292 ошибки: 191 статус (187 PENDING + 4 RFL CFG-02A), 90 strict-ошибок у 45 исторических VERIFIED без привязки к 113f (каждая дважды), 11 live-type; все 8 закрытых строк проходят |
| cfg review `--slice CFG-03` | 1 | 17: 14 до-существующих PENDING + 3 stage-type (03.4/.11/.12: production-эвиденс не принимается на review; release принимает) |
| cfg review `--slice CFG-02B` | 1 | 28: 14 исторических VERIFIED без привязки к 113f (по 2 strict-ошибки); строки .2/.2.3/.8 проходят |
| p0v plan | 0 | `inventory=24 manual=13 errors=0` |
| p0v release (`113f3a62`) | 1 | 40: 5 статус (4 PENDING + P0V-PIPE-CONTEXT RFL), 26 исторических VERIFIED без привязки, 9 live-type |
| p0v review `--slice P0V-PIPE` | 1 | 3: только исторические FALLBACK/WORKER/BEYOND без привязки; E2E проходит, CONTEXT RFL допустим на review |
| add-tr plan | 0 | `inventory=32 manual=36 errors=0` |
| add-tr review `--slice ADTR-POSTGEN` | 0 | `scoped=10 errors=0` (map candidate `948c2004`; acceptance-эвиденс дополнительно привязан к `113f3a62`) |

**Почему release rc=1 не отменяет Approved-приёмку:** это мульти-слайсовые карты; CFG-04..07 ещё
не построены/не задеплоены, исторические слайсы не перепривязаны к кандидату приёмки, а четыре
workflow/test-matrix строки P0V и один live-остаток (`P0V-PIPE-CONTEXT`) не закрываются этой волной.
Ни одна из закрытых строк не появляется в списке ошибок.

## 4. Девиации и границы

1. **ADTR-строки живут не в cfg-карте.** `ADTR-POSTGEN-*` находятся только в
   `plans/features/add-tr/requirements-map.json`. Лейн разрешал writer-доступ к картам `cfg`/`p0v`;
   чтобы исполнить прямые пункты задания (ADTR-POSTGEN-PENDING → VERIFIED, ON/OFF/DEDUP → RFL),
   изменены **ровно 4 строки** add-tr-карты. `candidate_commit`/`deployed_commit` add-tr не менялись,
   другие строки не тронуты. Это единственное расширение write-scope; код/прод не затрагивались.
2. **«Базовые маркеры» не являются отдельной строкой требования** ни в одной карте. Они зафиксированы
   production-эвиденсом в CFG-03.4 и P0V-PIPE-E2E и отдельным разделом лога/леджера, без выдуманной
   req_id.
3. **(b) postgen ready и (c) positive half** не заводились новыми строками: (b) представлено
   `ADTR-POSTGEN-ON` (RFL), (c) — `P0V-PIPE-CONTEXT` (RFL). Дублирующие req_id не создавались; остатки
   зафиксированы в note/live_note и evidence.
4. **Review-этап CFG-03** даёт 3 type-ошибки для 03.4/.11/.12, потому что review принимает только
   `live/ui/provider`, а эвиденс помечен `production` (release принимает `live/production`). Это
   ограничение stage-правила гейта, не дефект привязки; release-прогон эти строки принимает.
5. Секретов в добавленных путях нет; используются уже принятые REV-ACCEPT-95 артефакты.
