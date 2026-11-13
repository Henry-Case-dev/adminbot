# SELF-DIAG-01 corrective 2026-11-13 — привязка карты, gates и handoff

**Роль:** PM (map/evidence bindings only). Продукт, production и `plans/progress_scope.json` не изменялись.
**Owner input:** `plans/owner_inputs/2026-11-13-selfdiag-corrective-journal-code-identity.md` (§§0–9).
**Контракт:** `corrective-2026-11-13/architecture-corrective.md`.
**Композитный source карты:** `corrective-2026-11-13/source-selfdiag01-plus-corrective-2026-11-13.md`
(prefix = исходное ТЗ `2026-11-09-self-diag-01.md` verbatim, suffix = corrective verbatim; SHA-256 в карте).

## 1. Что добавлено в карту

Новые срезы (все — corrective, не новый эпик):

| Срез | Кандидат | Строк (required) | Статусы |
|---|---|---|---|
| `SELFDIG-CORRECTIVE-2026-11-13` | code `76fcb82962592a8e099239cd11e6c34ff13cf407`, docs `e5a92eba…` | 15 | 13 REVIEW, 2 READY_FOR_LIVE |
| `SELFDIG-CORRECTIVE-IDENTITY-2026-11-13` | code `ea9e9f2a1dc8b04bb82607acf9939bdefa3c16be`, docs `6639baa3…` | 4 | 3 REVIEW, 1 READY_FOR_LIVE |
| `SELFDIG-CORRECTIVE-JOURNAL-ENV-2026-11-13` | docs/env `1f2156ea` | 2 | 2 VERIFIED |
| `SELFDIG-CORRECTIVE-CLOSEOUT-2026-11-13` | релизный поезд (ещё нет) | 2 | 2 PENDING |

Строки (req_id → обязанность → существующая строка карты):

| req_id | Обязанность | Статус | Маппинг |
|---|---|---|---|
| `SD1-COR-01` | §1 инвариант: семантика вместо лексики, нет regex/словарей/скрытого fallback | REVIEW | усиливает `SD1-SEM-01/02/03/05/06/11`, `SD1-AC-05` |
| `SD1-COR-03` | §3 чекап = исследовательский tool-loop на существующей архитектуре | REVIEW | расширяет `SD1-EVD-01`, `SD1-D3-01`, `SD1-D4-01`, `SD1-D6-08`, `SD1-AC-02/03` |
| `SD1-COR-04` | §4 continuation, self-repo без ссылки, deployed/checkout/remote, локализация дефекта | REVIEW | расширяет `SD1-SEM-08`, `SD1-D4-03/05/06/07/08`, `SD1-AC-06` |
| `SD1-COR-05` | §5 деградация при пустом L1 без потери намерения и без autostart | REVIEW | расширяет `SD1-D6-09`, `SD1-GRAL-04` |
| `SD1-COR-09` | §7 сохранение доступов/настроек/стиля, без новых лимитов и OFF/SHADOW | REVIEW | подтверждает `SD1-D2-*`, `SD1-D6-01/03/04`, `SD1-D3-07`, `SD1-AC-21` |
| `SD1-COR-07` | §8.2 семантическая обобщаемость на незнакомых формулировках | REVIEW | расширяет `SD1-SEM-02/04/05/07` |
| `SD1-COR-08` | §8.3 обязательный антихардкод-аудит Reviewer | REVIEW | новое (аудит-обязанность), опирается на `SD1-GRAL-01` |
| `SD1-COR-EV` | §9 формат A–G evidence (correlation ID, маршрут, decision, tool, repo/ref/path/lines, ответ) | REVIEW | расширяет `SD1-AC-22`, `SD1-EVD-11`, `SD1-D7-04` |
| `SD1-COR-AC-A` | §8.1 A: реальный прод-чекап читает journald текущего invocation | **READY_FOR_LIVE** | расширяет `SD1-D1-02/13`, `SD1-D6-07`, `SD1-AC-02` |
| `SD1-COR-AC-B` | §8.1 B: модель сама читает код, прочитанное участвует в выводах | REVIEW | расширяет `SD1-AC-03`, `SD1-D6-08` |
| `SD1-COR-AC-C` | §8.1 C: продолжение → Writer → отправленный ответ без просьбы о ссылке | REVIEW | расширяет `SD1-AC-22`, `SD1-SEM-08` |
| `SD1-COR-AC-D` | §8.1 D: пустой L1 → резервный механизм/честная деградация | REVIEW | расширяет `SD1-D6-09`, `SD1-GRAL-04` |
| `SD1-COR-AC-E` | §8.1 E: недоступные источники ≠ ноль | REVIEW | расширяет `SD1-EVD-08/09`, `SD1-D6-09` |
| `SD1-COR-AC-F` | §8.1 F: негативный RBAC | REVIEW | расширяет `SD1-D2-09/19`, `SD1-D5-07`, `SD1-AC-11` |
| `SD1-COR-LIVE-TELEGRAM` | §4/§8.1 C на проде: Telegram-ответ + continuation | **READY_FOR_LIVE** | расширяет `SD1-AC-01/09`, `SD1-EVD-02` |
| `SD1-COR-ID-01` | §6 producer манифеста фактического SHA до рестарта, rollback/dry-run | REVIEW | новое (в базе producer отсутствовал) |
| `SD1-COR-ID-02` | §6 manifest/process/checkout, честный mismatch, checkout ≠ deployed | REVIEW | расширяет `SD1-D4-05/06/08`, `SD1-EVD-10` |
| `SD1-COR-ID-03` | §6 честные счётчики journal/Telegram/STT (null/not_checked вместо нуля) | REVIEW | расширяет `SD1-D6-17/18/19/20` |
| `SD1-COR-LIVE-MANIFEST` | §8.1 G на проде: deployed identity после ближайшего релиза | **READY_FOR_LIVE** | новое (production-only) |
| `SD1-COR-J1` | §2 чтение реального journald сервисным пользователем, без root/sudo/sandbox | **VERIFIED** (DevOps evidence) | расширяет `SD1-D1-02/13`, `SD1-D6-07` |
| `SD1-COR-J2` | §2 персистентность фикса, unit не изменён, внешние collectors не возвращены | **VERIFIED** (DevOps evidence) | расширяет `SD1-D1-14`, `SD1-GRAL-04` |
| `SD1-COR-CL-01` | §9 единый релизный поезд + доступный production smoke до DONE | PENDING | процесс релиза (`SD1-D7-04`) |
| `SD1-COR-CL-02` | §9 финальный отчёт (4 обязательных пункта) | PENDING | процесс отчёта (`SD1-D7-06`) |

Дублирующих строк не создано: для каждой обязанности указано, какую существующую строку она расширяет
(`legacy_refs` + `mapping_decision` в карте). Самостоятельные обязанности — только реально новые:
инвариант §1 как отдельная приёмка, аудит §8.3, формат A–G §9, producer манифеста, production-срезы A/C/G,
средовой journal-фикс §2, релизный closeout §9.

**Классификация source:** композитный source даёт 141 новую deterministic-строку; все классифицированы
(132 `duplicate` с указанием req_id, 9 `context` с конкретной причиной), 0 несмапленных.
Проверок `source item not mapped` — нет.

## 2. Почему такие статусы

- **REVIEW** — код/док-кандидат реализован и независимо одобрен, но не выложен. По контракту карты
  `VERIFIED` = подтверждённое поведение на выложенном кандидате; до релиза backend-строки остаются REVIEW.
- **READY_FOR_LIVE** — доказательство физически возможно только на выложенном боте: сквозной journald-путь
  через реальный чекап (A), production Telegram/continuation (C), deployed manifest (G). Все три имеют
  `live_required: true`, `live_when: postdeploy`, `postrelease_wait` (nonblocking, trigger, next_check, owner=agents,
  contract_ref) и candidate-bound Reviewer approval с тем же объектом `approved_postrelease_wait`.
- **VERIFIED** — только средовой journal-фикс §2 (J1/J2): доказательство — production evidence DevOps
  (`journal-access-evidence.md`, commit `1f2156ea`), не код-кандидат. Сквозной чекап через журнал сюда **не**
  входит — он в `SD1-COR-AC-A` (READY_FOR_LIVE), как и требуется owner input §2.
- **PENDING** — релизный поезд и финальный отчёт §9; это не инженерная работа PM.

## 3. Gates (точные выводы, self-diag map, `--repo C:\Code\Python\adminbot`)

| Gate | Команда (сокращённо) | Вывод | Exit |
|---|---|---|---|
| plan | `--stage plan` | `stage=plan inventory=324 manual=76 scoped=0 errors=0` | 0 |
| review core | `--stage review --slice SELFDIG-CORRECTIVE-2026-11-13 --candidate 76fcb829… --strict-evidence` | `stage=review inventory=324 manual=76 scoped=15 errors=0` | 0 |
| review identity | `--stage review --slice SELFDIG-CORRECTIVE-IDENTITY-2026-11-13 --candidate ea9e9f2a… --strict-evidence` | `stage=review inventory=324 manual=76 scoped=4 errors=0` | 0 |
| review journal-env | `--stage review --slice SELFDIG-CORRECTIVE-JOURNAL-ENV-2026-11-13 --candidate 1f2156ea --strict-evidence` | `stage=review inventory=324 manual=76 scoped=2 errors=0` | 0 |
| deploy core | `--stage deploy --slice SELFDIG-CORRECTIVE-2026-11-13 --candidate 76fcb829… --strict-evidence` | `stage=deploy inventory=324 manual=76 scoped=15 errors=27` | **1** |
| deploy identity | `--stage deploy --slice SELFDIG-CORRECTIVE-IDENTITY-2026-11-13 --candidate ea9e9f2a… --strict-evidence` | `stage=deploy inventory=324 manual=76 scoped=4 errors=39` | **1** |

### 3.1 Разбор красного deploy-gate (не «зеленить»)

Все ошибки обоих прогонов — **только dependency-closure** по `depends_on` графа:

- core: D2 — 4, D3 — 2, D4 — 3, D5 — 3, D6 — 15 (всего 27);
- identity: те же + D7 — 12 (всего 39).

Ни одна ошибка не относится к `SD1-COR-*` (проверено `Select-String 'SD1-COR-'` → 0 совпадений): собственные
строки коррективы прошли per-row проверки deploy-стадии (candidate-bound evidence + Reviewer approval, включая
deferred-строки с совпадающим `approved_postrelease_wait`).

Причина красного честная: строки зависимых срезов — `READY_FOR_LIVE` (live-доказательства появляются только
после выкладки). То есть **правило независимого scoped-релиза здесь принципиально неприменимо**: коррективa
меняет поведение, впервые выкладываемое этим же релизом, а её live-доказательства не могут существовать раньше.

**Следствие для Orchestrator/DevOps:** не пытаться выпускать corrective через `--slice`. Релиз идёт общим
**epic-level** gate по объединённому релизному кандидату (как 2.58.198: `stage=deploy … scoped=189 errors=0`),
с привязкой evidence к релизному кандидату и последующим `--stage release` после фактической выкладки.
Коррективa и identity-кандидат должны быть сведены в один релизный поезд.

`deploy` для journal-env не запускался: изменений кода нет, среда уже исправлена; deploy-gate требует
Reviewer-approval для VERIFIED-строк, что неприменимо к средовому фиксу (доказательство — production evidence).

## 4. Итоговые счётчики self-diag

- Записей inventory: 324 (183 исходных + 141 corrective); manual-строк: 76 (53 + 23).
- Required-записей: 212; уникальных req_id: 206.
- По уникальным req_id: **VERIFIED 147, READY_FOR_LIVE 41, REVIEW 16, PENDING 2**.
- REVIEW = 13 core + 3 identity; READY = 40 прежних + AC-A + LIVE-TELEGRAM + LIVE-MANIFEST; PENDING = CL-01/CL-02.
- Пакеты: `slice_candidate_bindings.corrective` (code/docs/base/branches, review+binding+sha256, identity/journal
  evidence, A–G/semantic/audit артефакты, тесты 28/330/442/p4 + 4 pre-existing на базе, DDL 0, residual) и
  отдельные ключи на каждый новый срез для slice-gate.
- `corrective_2026_11_13_accounting.gates_2026_11_13` — точные команды/выводы/exit, включая объяснение красного deploy.

## 5. Остаточное (честно)

1. Production: A (journal end-to-end), C/Telegram, G (manifest) — READY_FOR_LIVE до релиза и наблюдения.
2. CL-01/CL-02 — релизный поезд и финальный отчёт §9.
3. BACKLOG_ONLY вне scope: `web/api/routes.py::_self_diag_payload` читает `identity.branch/source`, которых нет
   в top-level (identity binding §7.7); влияет на отображение branch/source, не на deployed_sha/healthy/counters.
4. Evidence-quality (не блокер): в `ag-traces-76fcb829.json` русские строки ответов записаны в двойной
   кодировке; структура, correlation ID, пути/строки и статусы читаемы, поведение не затронуто.

## 6. Провенанс review-артефактов

- `review-identity-ea9e9f2a.md` — авторский файл Reviewer (забран из worktree identity без правок).
- `review-core-76fcb829.md` — вердикт независимого Reviewer, переданный Orchestrator, зафиксирован PM без
  собственных выводов (reviewer-файла на ветке не было). Если Reviewer выпустит свой авторский файл, карта
  перепривязывается на него без изменения строк.
- `anti-hardcode-audit-76fcb829.md` — механический скан PM (вспомогательный, не замена аудита Reviewer).

## 7. Предлагаемая дельта `plans/progress_scope.json` (не применялась PM)

- Task `self-diag-01`: `status` остаётся **не DONE**; corrective-состояние:
  `REVIEW 16 / READY_FOR_LIVE 41 / VERIFIED 147 / PENDING 2` по уникальным req_id;
  срезы `SELFDIG-CORRECTIVE-*` добавлены как часть того же эпика (не новые задачи).
- Зарегистрировать/подтвердить: реализация коррективы готова к релизному поезду (core+identity), journal-доступ
  закрыт (VERIFIED); production-доказательства A/C/G — postdeploy, nonblocking.
- Заблокировать независимый scoped-релиз коррективы; разрешён только epic-level релиз по объединённому кандидату.
- Следующее действие Orchestrator: включить corrective core (76fcb829) + identity (ea9e9f2a) в один релизный
  кандидат, назначить DevOps epic-release gate + production smoke, после выкладки — release/delivery reconciliation
  READY-строк и CL-01.

## 8. Статус эпика

**SELF-DIAG-01 НЕ DONE.** Коррективa остаётся REVIEW/READY_FOR_LIVE до релизной выкладки, production smoke и
остаточных production-доказательств. Родительский эпик не переоткрывается: закрываются только строки коррективы
после фактического наблюдения.
