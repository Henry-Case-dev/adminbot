# ADR-1026-23 — A10 «Agentic Verification»: read-only верификационный гейт Эпика 3 (§52–§54) — собственный Reviewer gate, deploy `epic deployment not applicable`, приёмочный отчёт в `plans/reports/`, гибридная политика watch-items (CLOSE/PASS-THROUGH), defect-handling через отдельную фичу/агрегатный блокер, merge §92, агрегатный handoff-контракт, R1

- **Статус:** **Accepted** (merge to `plans/ARCHITECTURE.md` **§92**, 25.09.2026, T-3727 @Architect; §91 A9 — последний раздел, §92 свободен — verified). **Accepted = решение принято и включено в pending epic-release Эпика 3; НЕ «deployed»** — release policy **EPIC_ONLY**, deployment A10 **`epic deployment not applicable`** (пер-фича деплоя/тега/bump нет; `APP_VERSION` **2.58.30**; агрегатный bump **2.58.30 → 2.58.31** — на границе эпика).
- **Фича:** A10 `agentic-verification-round1026` (Эпик 3 «Agentic Intelligence», Wave 5 — продолжение; Раунд 10.26). **P0. ПОСЛЕДНЯЯ фича Эпика 3.**
- **Тип** (`backlog:312`): **verification (gate), read-only** — верифицирует A0–A9, не переписывает фичи/тесты; продукт-код не пишется. **Зависит от:** A0–A9 ✅.
- **ТЗ-основание:** `plans/current_task.md` **§52** (`:5748–5804`; 23 сценария + closing-правило `:5803–5804`), **§53** (`:5806–5851`; 15 критериев), **§54** (`:5852–5889`; 12 результатов). IMMUTABLE, read-only (R17/R18).
- **Baseline (Step 0 @Memory, 25.09.2026):** HEAD **`e8646af`** + **UNCOMMITTED epic-release дерево A2–A9** — не трогать/не коммитить; `APP_VERSION` **2.58.30**; канон **12**; SQLite **v12**; Δ DDL=0; счётчики каталога **`473/430/448/102/100/21`**; pytest **9513/0**; JS **47/47**; анкер отката **`e8646af`**.
- **Первый-класс прецедент (REUSE):** **F10 `epic1-verification-round1025`** — `plans/archive/epic1-verification-round1025/` (`tasks.md` T-3121 собственный Reviewer gate; `adr-1025-24-verification-gate.md` D1 NOT_APPLICABLE/he изотчет в `plans/reports/`; `spec.md`; `deployment.md` NOT_APPLICABLE). A10 **повторяет форму F10** для Эпика 3.
- **Связано:** ADR-1026-22 (A9 §91), ADR-1026-21 (A8), ADR-1026-20 (A7), ADR-1026-19 (A4), ADR-1026-18 (A6), ADR-1026-17 (A5), ADR-1026-16 (A3), ADR-1026-15 (A2), ADR-1026-14 (A1), ADR-1026-13 (A0), ADR-1025-24 (F10 — REUSE). **Вне scope:** §52–§54 реализация, product-код, деплой.

## Контекст

Эпик 3 «Agentic Intelligence» (A0–A9) завершён на уровне фич: A0 (read-only аудит, `plans/docs/agentic-audit-round1026.md`), A1 (`CoordinatorDecision`), A2 (цепочки/лимиты §15–§17), A3 (единый `ImageRequest`), A4 (память/RAG изображений), A5 (дневной лимит + DDL `image_reservation`), A6 (`get_user_context`), A7 (Decision Making `action`/`style`), A8 (механика реакции), A9 (события §49 + ExecutionGraph §51). Все приняты в **pending epic release** (deployment DEFERRED_TO_EPIC), кроме A1 (deployed 2.58.30).

**A10 — финальный верификационный гейт**, который обязан доказать §52 (23 сценария), §53 (15 критериев «Эпик 3 не завершён, если…») и §54 (12 результатов), **не переписывая** A0–A9 и **не создавая** product-код. Ключевое ограничение §52 (`:5803–5804`): **«Не считать один успешный тест достаточным подтверждением архитектуры»** — приёмка по живым артефактам, а не по одному тесту/сборке. Часть сценариев (1/2/4/10/18/22) зависит от **живых прод-проб/Telegram WebView**, недоступных headless-контуру → честный `PENDING OWNER VERIFICATION` (прецедент A3/A5/F10), **никогда не закрывается**.

**Открытые вопросы Step 1 (tasks.md 1–8)** требуют lasting-решений: (1) собственный gate vs внутри-агрегатный; (2) deploy-вердикт; (3) место отчёта; (4) политика watch-items; (5)/(6) F2/F-9 и defect-handling; (7) merge-раздел; (8) threat-артефакт. Дополнительно фиксируются: read-only scope и **агрегатный handoff-контракт** (вход агрегатного Reviewer release gate).

**Фактическое состояние baseline (verified на Step 2).**
- Merge-разделы: `ARCHITECTURE.md` §82 (A0) … **§91 (A9)**; **§92 — следующий свободный** (проверено: §91 — последний `## `-раздел, `## 92.` отсутствует).
- Отчётная конвенция F10: `plans/reports/round1025_f10_acceptance.md` (verified существует) → A10: **`plans/reports/round1026_a10_acceptance.md`**.
- F10 gate: `tasks.md` T-3121 `[@Reviewer]` — **собственный** gate верификации; `T-3126 [@DevOps]` — **NOT_APPLICABLE** с обоснованием; `deployment.md` фиксирует вердикт.
- Watch-item register Эпика 3 — 11 групп (`tasks.md:188–202`): L-A9-3702-01…04; дискрепансия имени тест-файла A9; D-3 untracked archive; ADR hash re-pins (ADR-1026-20/21/22); T-3667/T-3668 (архив A8); F-9/R-set (A7); C4-N1/C4-N2/N2 (A4); F1–F7 (A5); L-A6-01…06 (A6); owner-gate A3; среда/док (BetterStack-флейк, `backlog:29` 22→23, `backlog:314`, F0.3 `ANTI_CLICHE_*`).

## Решения

> **Соответствие нумерации:** open questions `tasks.md` 1–8 ↔ D1–D8 (Q5 F2/F-9 ↔ **D6**; Q6 defect-handling ↔ **D5** — перестановка из-за порядка, заданного Step 2). D9 = read-only scope; D10 = агрегатный handoff-контракт.

**D1 (Q1). Собственный Reviewer gate A10 — да; агрегатный gate — отдельный последующий шаг.**
- A10 получает **собственный единый Reviewer gate T-3726** (обе линзы: requirements/correctness + focused change-audit; Scanner удалён 24.09.2026) с binding Reviewed-Commit / Working-Tree-Hash / Spec-Hash.
- **Агрегатный Reviewer release gate Эпика 3 — отдельный шаг после A10** (T-3729); он **не** заменяет A10-гейт и наоборот. A10 не сертифицирует сам себя (нет self-certification).
- **Обоснование:** прецедент F10 (T-3121); иначе финальное ревью верификации «растворяется» в релизном.
- **Альтернативы:** приёмка только внутри агрегатного gate — отклонено (потеря отдельной верификационной линзы, self-certification-риск); A10 без Reviewer — отклонено (нарушает единый gate-паттерн эпика).

**D2 (Q2). Deploy-вердикт A10 = `epic deployment not applicable`.**
- A10 не поставляет рантайм (read-only: feature-папка + `plans/reports/**`); bump `APP_VERSION` внутри A10 **не делается** (`2.58.30`); **@DevOps внутри A10 не вызывается**; пер-фича тега нет.
- A10 входит в pending epic release **как gate/evidence-артефакт**, не как поставляемый рантайм. Агрегатный bump **2.58.30 → 2.58.31** (включая миграцию A5) — на границе эпика после агрегатного approval.
- **Обоснование:** `APP_VERSION` маркирует поставляемый рантайм; у A10 рантайм-вклада нет → bump был бы ложным сигналом (прецедент F10/ADR-1025-24 D1, F8 §67.3).
- **Альтернативы:** `DEFERRED_TO_EPIC` — отклонено (нечего откладывать: нет рантайм-вклада A10); deploy + bump «для порядка» — отклонено (ложный сигнал).

**D3 (Q3). Место/форма приёмочного отчёта = `plans/reports/round1026_a10_acceptance.md`.**
- Evidence/review — в feature-папке: `plans/features/agentic-verification-round1026/{evidence.md, review-T-3726.md}`; при архивации — `plans/archive/agentic-verification-round1026/`.
- Обязательные разделы отчёта — spec §7.1 (provenance; §52 23 сценария; §53 15 критериев; §54 12 результатов; эпик-wide числа; найденные дефекты; watch-item register; owner-gate register; список «НЕ принято»; вердикт).
- **Обоснование:** прецедент F10 (`plans/reports/round1025_f10_acceptance.md` — verified).
- **Альтернативы:** отчёт только в feature-папке — отклонено (F10-конвенция отчётов в `plans/reports/`).

**D4 (Q4). Политика watch-items — гибрид CLOSE / PASS-THROUGH (без «тихого» закрытия).**
- **CLOSED in A10** — только то, что полностью разрешается read-only-проверкой/диспозицией (evidence в отчёте; product-код не меняется). **PASS-THROUGH** — всё, что требует продукт-изменений, релизных операций, re-pin хэшей, стейджинга или внешнего владельца. **PENDING (owner)** — внешние гейты.
- Детальная раскладка 11 групп — spec §9. Итог: CLOSED — группы 1, 2, 6, 7, 8, 9, 11; PASS-THROUGH — 3, 4, 5, 7(residual), 9(residual), 11(флейк/маркеры); PENDING — 10 (owner-gate A3).
- **Обоснование:** read-only реально закрывает не всё; релизные/внешние пункты принадлежат агрегатному gate/владельцу; «тихое» закрытие запрещено (инвариант 7).
- **Альтернативы:** закрыть всё в A10 — отклонено (потребовало бы правок A0–A9/релизных операций, нарушает read-only); всё на агрегатный gate — отклонено (потеря проверяемых диспозиций).

**D5 (Q6). Defect-handling: рантайм-дефект, найденный верификацией, НЕ фиксится внутри A10.**
- Путь: **(a)** отдельная фича/hotfix с собственной санкцией/ревью/деплоем, либо **(b)** регистрация как **release-блокера** агрегатного gate (если блокирует релиз Эпика 3).
- Reporting path: раздел отчёта «Найденные дефекты (не исправлены в A10)» → watch-item register → эскалация @Orchestrator → новая фича/hotfix или агрегатный блокер. Product-код в A10 остаётся нетронутым.
- **Обоснование:** F10 / ADR-1025-24 D1 — «тихий фикс» внутри верификации запрещён (риск скрытого изменения рантайма без отдельного gate).
- **Альтернативы:** исправить в A10 — прямо запрещено (read-only, R1); проигнорировать — запрещено (приёмка обязана сообщить).

**D6 (Q5). Диспозиция F2/F-9 — документировать как accepted boundary (без отдельной санкции).**
- **A5 F2** (verbose/cover-путь остаётся legacy `consume` — документированная граница) и **A7 F-9** (ослабленный forbidden-path тест A1-boundary) фиксируются в watch-item register как **registered non-blocking** (уже приняты на своих feature-гейтах).
- Отдельная санкция/hotfix **не требуется**, пока @Reviewer A10/агрегатный gate не повысят до блокера — тогда путь D5. A10 **не переписывает** ослабленный тест (read-only).
- **Обоснование:** оба приняты non-blocking на своих гейтах; read-only-периметр не позволяет править тест/код.
- **Альтернативы:** отдельная санкция сейчас — отклонено (избыточно, оба non-blocking); проигнорировать — запрещено (регистрация обязательна).

**D7 (Q7). Merge-раздел = `plans/ARCHITECTURE.md` §92 (следующий свободный после §91).**
- T-3727: merge §92 @Architect; ADR-1026-23 → Accepted; фиксируется статус «Эпик 3 авто-верифицирован (A10); live-owner-гейты PENDING; агрегатный release gate — следующий шаг», **без** объявления эпика «DEPLOYED-завершённым».
- Детальный агрегатный handoff-контракт — D10.
- **Обоснование:** verified §91 — последний `## `-раздел; `## 92.` отсутствует.
- **Альтернативы:** отдельный ADR-раздел/новый документ — отклонено (нарушает merge-конвенцию §82–§91).

**D8 (Q8). `threat-failure-analysis.md` при R1 = `NOT_APPLICABLE`.**
- Артефакт не создаётся. Эскалация: при подъёме Risk до R2/R3 (изменение тест-харнесса с рантайм-импортом; миграционный дефект A5; утечка R17) — артефакт **обязателен**.
- **Обоснование:** read-only, без рантайма/DDL/каталога (прецедент F10; A8/A9 при R2).
- **Альтернативы:** создать «на всякий случай» — отклонено (нет threat-поверхности).

**D9. Read-only scope definition (инвариант).**
- A10 **не** правит A0–A9-архивы/`spec.md`/ADR/код; **не** дублирует фичевые тесты; изменения — только `plans/features/agentic-verification-round1026/**` + `plans/reports/**`. Product-код, миграции, каталог, `config/settings.py`, `current_task.md`, машинный блок — **вне diff**.
- Харнесс **переиспользуется как есть** (прецедент F10); аддитивное расширение — только по отдельной санкции с поднятием Risk до **R2** (без рантайм-импорта).
- A0–A9-артефакты **только чтение**; owner-гейты **никогда не репортятся закрытыми**.

**D10. Агрегатный Reviewer release gate: обязательный handoff-контракт.**
- **Mandatory вход агрегатного gate:** приёмочный отчёт A10 + watch-item register + чек-листы §52/§53/§54.
- Агрегатный gate дополнительно обязан покрыть: полный эпик-diff **A2–A9+A10**; кросс-фичевые взаимодействия; интеграцию/регресс; миграции (**A5 DDL** — `image_reservation` + индексы); конфиг/наблюдаемость (env-only kill-switches, каталог, R17-логи); обратную совместимость; безопасность (R17/R18); готовность отката (анкер `e8646af` + per-feature kill-switches + путь отката миграций); согласованность с каждой принятой feature-spec; **binding** к точному релиз-коммиту + детерминированному working-tree-hash + агрегатному spec-manifest-hash.
- Только после агрегатного approval — доставка + @DevOps bump **2.58.30 → 2.58.31**.
- **Обоснование:** A10 — финальный verification-гейт эпика; вывод A10 = **вход** агрегатного gate, не его замена (инвариант 12).

## Санкции и вердикты (verbatim-critical)

- **Тип/периметр:** verification/read-only; product-код не пишется; A0–A9 не переписываются; тесты не дублируются.
- **Gate:** собственный Reviewer gate A10 (**T-3726**); агрегатный gate — отдельный шаг после.
- **Deploy:** **`epic deployment not applicable`**; @DevOps внутри A10 не вызывается; `APP_VERSION` **2.58.30**; агрегатный bump 2.58.31 — на границе эпика.
- **Отчёт:** `plans/reports/round1026_a10_acceptance.md` (D3).
- **Watch-items:** 11 групп, CLOSE/PASS-THROUGH/PENDING без «тихого» закрытия (D4/spec §9).
- **Defect:** не фикс в A10 → отдельная фича/hotfix или агрегатный блокер (D5).
- **Risk:** **R1**; threat-артефакт **`NOT_APPLICABLE`** (D8); повышение до R2/R3 → обязателен.
- **Merge:** §92; ADR → Accepted (D7).
- **Инварианты:** Δ DDL=0 (SQLite v12); Δ каталога=0 (`473/430/448/102/100/21`); канон **12**; нет нового инструмента/3-го LLM-вызова; §104 `generate_image` — no-go; R17/R18; owner-гейты PENDING. **Исключение:** A5 DDL `image_reservation` — существующая sanctioned-миграция эпика, применяется агрегатным релизом, **не** A10.
- **Release policy:** EPIC_ONLY.

## AMEND / REUSE-карта

| ADR / артефакт | Статус в A10 | Суть |
|---|---|---|
| **ADR-1025-24** (F10 verification gate) | **REUSE (первый-класс прецедент)** | read-only verification, deploy NOT_APPLICABLE, отчёт в `plans/reports/`, собственный Reviewer gate, owner-гейты PENDING — форма A10 |
| **F10 `epic1-verification-round1025`** (`tasks.md` T-3121/T-3126) | **REUSE (форма и конвенции)** | собственный Reviewer gate; `plans/reports/round1025_f10_acceptance.md` → отчётная конвенция |
| **ADR-1026-22** (A9 §91) | **REUSE (предшественник merge)** | §91 — последний раздел; §92 — merge A10; A9 event-артефакты — evidence для §52/§53/§54 |
| **ADR-1026-21/-20/-19/-18/-17/-16/-15/-14/-13** | **REUSE (потребляются как контракты)** | A8/A7/A4/A6/A5/A3/A2/A1/A0 — предмет верификации; не переписываются |
| **`tasks.md` A10 (T-3706…T-3729)** | **REUSE / вход** | REQ-A10-01…-51, 12 инвариантов, watch-items, scenario-map |
| **`plans/docs/agentic-audit-round1026.md`** (A0) | **REUSE (evidence)** | `#tool-map`/`#root-cause` (HY-01…HY-06)/`#duplicates` |
| **F8 re-issue (ADR-1026-2)** | **NOT_APPLICABLE** | Δ каталога = 0 |
| **ADR-1013-3** (промпты) | **NOT_APPLICABLE** | промпты/JSON-схемы не меняются |
| **§52/§53/§54** | **предмет верификации (verbatim)** | 23 сценария + closing; 15 критериев; 12 результатов |

| Решение | Задачи (`tasks.md`) |
|---|---|
| D1 (собственный gate) | T-3726 |
| D2 (deploy NOT_APPLICABLE) | T-3728 |
| D3 (отчёт `plans/reports/`) | T-3724 |
| D4 (watch-items CLOSE/PASS-THROUGH) | T-3722 |
| D5 (defect-handling) | T-3724, T-3726 |
| D6 (F2/F-9 dispositions) | T-3722, T-3724 |
| D7 (merge §92) | T-3727 |
| D8 (threat N/A) | T-3726 |
| D9 (read-only scope) | T-3720, T-3721, T-3726 |
| D10 (агрегатный handoff) | T-3729 |

## Альтернативы (сводно)

| Вопрос | Рассмотрено | Выбор | Почему |
|---|---|---|---|
| Gate (Q1) | свой gate; внутри агрегатного | **свой T-3726** | F10 T-3121; нет self-certification |
| Deploy (Q2) | NOT_APPLICABLE; DEFERRED_TO_EPIC | **`epic deployment not applicable`** | нет рантайм-вклада; bump на границе |
| Отчёт (Q3) | feature-папка; `plans/reports/` | **`plans/reports/round1026_a10_acceptance.md`** | конвенция F10 |
| Watch-items (Q4) | всё закрыть; всё passed | **гибрид CLOSE/PASS-THROUGH** | read-only закрывает не всё |
| Defect (Q5) | фикс в A10; отдельная фича | **отдельная фича/hotfix/блокер** | F10/ADR-1025-24 D1 |
| F2/F-9 (Q6) | санкция; документировать | **accepted boundary** | уже non-blocking на своих гейтах |
| Merge (Q7) | §92; иное | **§92** | verified свободен |
| Threat (Q8) | создать; N/A | **NOT_APPLICABLE (R1)** | нет threat-поверхности |
| Харнесс | расширять; переиспользовать | **переиспользовать** | F10; минимизация blast radius |
| Risk | R2; R1 | **R1** | read-only, без рантайма/DDL/каталога |

## Последствия

- §52 (23 сценария) проверены с evidence-ref; owner-гейты (1/2/4/10/18/22) — `PENDING OWNER VERIFICATION`, не закрыты; §52 closing-правило соблюдено (приёмка по живым артефактам).
- §53 (15 критериев) — каждый со статусом/evidence; Эпик 3 **не** объявляется завершённым при непройденном критерии.
- §54 (12 результатов) — каждый связан с существующим артефактом/разделом §82–§91; выдуманных деливераблов нет.
- Watch-items (11 групп) — раскладка CLOSE/PASS-THROUGH/PENDING; «тихое» закрытие отсутствует.
- Собственный Reviewer gate A10 → merge §92 → handoff агрегатному gate (D10); deploy `epic deployment not applicable`; `APP_VERSION` 2.58.30; @DevOps внутри A10 не вызывается.
- Затронутые контракты: ни один рантайм-контракт не меняется. Инварианты Δ DDL=0, Δ каталога=0, канон 12, R17/R18 — сохраняются. A5 DDL — существующая sanctioned-миграция эпика (применяется агрегатным релизом, не A10).
- **Handoff:** вывод A10 — обязательный вход агрегатного Reviewer release gate Эпика 3 (T-3729), не его замена.

## Ссылки

- `plans/features/agentic-verification-round1026/{spec.md, tasks.md}` (spec — Step 2 T-3708; сверка — @PM T-3709).
- ТЗ: `plans/current_task.md` §52 (`:5748–5804`), §53 (`:5806–5851`), §54 (`:5852–5889`).
- Прецедент: `plans/archive/epic1-verification-round1025/{tasks.md, spec.md, adr-1025-24-verification-gate.md, deployment.md}`; отчёт — `plans/reports/round1025_f10_acceptance.md` (verified).
- Durable-аудит A0: `plans/docs/agentic-audit-round1026.md` (`#tool-map`, `#root-cause`, `#duplicates`).
- Архитектура: `plans/ARCHITECTURE.md` §82 (A0) … §91 (A9); ожидаемый merge — **§92** (verified: следующий свободный).
- Архивы A0–A9: `plans/archive/{agentic-audit, tool-coordinator, tool-chains, unified-image-request, image-daily-limit, memory-lookup-api, image-context-memory, decision-making, telegram-reactions, agentic-events-graph}-round1026/`.
- Код (baseline `e8646af` + незакоммиченное epic-release дерево A2–A9): `services/image_generation.py`, `services/image_context_memory.py`, `services/worker_budget.py`, `services/tool_router.py`, `services/tool_schemas.py`, `services/direct_chat_service.py`, `services/smartmodule_utils.py`, `services/agentic_events.py`, `services/execution_graph_source.py`.
- Точка отката: коммит **`e8646af`** (пер-фича тега не создаётся — EPIC_ONLY).
