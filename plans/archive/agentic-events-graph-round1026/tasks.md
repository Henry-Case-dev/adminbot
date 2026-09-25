# A9 — `agentic-events-graph-round1026` (Эпик 3 «Agentic Intelligence», Wave 5 (продолжение), Раунд 10.26)

> **Статус ЗАКРЫТИЯ A9 (T-3702…T-3705, 25.09.2026): ✅ A9 ЗАКРЫТ на 1-м цикле единого Reviewer gate — Approved C0/H0 (`review-T-3702.md`; binding Reviewed-Commit `e8646af`, Working-Tree-Hash `84d6df00…`, Spec-Hash `3f703584…`; Risk R2; Scanner отсутствует).**
> **T-3702 ✅ Approved (cycle 1, binding) · T-3703 ✅ ARCHIVED (`plans/archive/agentic-events-graph-round1026/`, 5 файлов; SHA-256 до/после идентичны; `threat-failure-analysis.md` отсутствует — `NOT_APPLICABLE` при R2/D1) · T-3704 = `DEFERRED_TO_EPIC` (accepted into pending epic release 3; НЕ deployed/НЕ `VERIFIED`; hot=`AGENTIC_EVENTS_ENABLED` OFF; cold=`git revert e8646af`; Δ DDL=0) · T-3705 ✅ handoff → A10.**
> **▶️ Следующая и ПОСЛЕДНЯЯ фича Эпика 3 — A10 `agentic-verification` (canonical `backlog:312`; §52–§54; P0; зависит A0–A9). После A10 — агрегатный Reviewer release gate Эпика 3 (все фичи approved → агрегатное ревью релиза → доставка + @DevOps bump 2.58.30 → 2.58.31).**
>
> **Статус (Step 2 @Architect + сверка @PM, T-3689/T-3690, 25.09.2026): `PLANNING_CONSISTENT` ВЫДАН.** `spec.md` (14 REQ-A9 → **SC-A9-01…-16**, 14 инвариантов, U1–U13) + **ADR-1026-22** (D1–D14, U1–U13 закрыты) созданы (T-3689); `tasks.md` сверен с ними (T-3690): SC/ADR-колонки заполнены, карта D1–D14→T-3689…T-3705 собрана, 14 инвариантов привязаны к SC, U1–U13 закрыты D-ссылками, анкер `anticliche_worker._event:80` исправлен. **Product-код не писан.** **Risk — `R2` ФИНАЛЬНЫЙ** (D1: in-memory расширение `RunSnapshotStore`, Δ DDL=0; `threat-failure-analysis.md` НЕ требуется). Architect по факту выбрал in-memory (DDL-ветка отклонена) → R3/threat-артефакт **N/A**; Reviewer может повысить по фактическому diff. **Build разрешён — следующий шаг Step 3 @Builder (T-3691…T-3701); затем Step 4 @Reviewer (T-3702, единый gate; @Scanner отсутствует).**
> **Эпик:** Эпик 3 «Agentic Intelligence», **Wave 5 (продолжение)**. **Verification note:** в `plans/backlog.md` явной Wave-метки для A9 нет; **A8 помечена «Wave 5 (продолжение)»** (`backlog:296/334`) — трактуем A9 как **продолжение Wave 5** (не изобретаем Wave 6). **Подтверждено `spec.md`/ADR-1026-22 (Wave 5 продолжение).**
> **Тип** (`backlog:311`): **backend/лог + web adapter** — события диагностики решений §49 + интеграция в существующий ExecutionGraph §51 + поверхность отображения Mini App §50. **P1**. **Зависит от:** **A1–A8** ✅ (все завершены; A8 → §90, ADR-1026-21 Accepted). **Включает L-1 follow-up** (из review T-3683). **Pacing:** A9 **предшествует** A10 по зависимости (A10 зависит от A0–A9; `backlog:312`) — A9 нельзя пропустить/отложить за A10.
> **Epic-ID:** Эпик 3 «Agentic Intelligence» (раунд 10.26). **Release policy — EPIC_ONLY:** эта фича — `included in pending epic release`; deployment **`DEFERRED_TO_EPIC`** (пер-фича деплоя/тега/bump нет; @DevOps не вызывается; агрегатный bump **2.58.30 → 2.58.31** — на границе эпика).
> **ТЗ-источник (IMMUTABLE, `plans/current_task.md`, только чтение — R17/R18):** **§49 «ДИАГНОСТИКА РЕШЕНИЙ»** (`:5634–5681`; содержательные `:5638–5680`), **§51 «ИНТЕГРАЦИЯ С КАРТОЙ ВЫЗОВОВ»** (`:5719–5747`; содержательные `:5723–5746`), **§50 «ИНТЕГРАЦИЯ С MINI APP»** (`:5682–5718`) — **граница отображения** (см. ниже). **Приёмочный ориентир:** **§53** «по логам невозможно понять, почему инструмент не сработал» (`:5846–5847`) — failure criterion, который A9 закрывает; **§52** (23 сценария, `:5754–5801`; `backlog:312` указывает «22» — расхождение зафиксировано для doc-maintenance, **не правим сейчас**).
> **§50 — ГРАНИЦА (не scope-расширение):** §50 для A9 — **INTEGRATION POINT / display surface only**. Настройки §50 **уже поставлены** A4/A5/A7/A8 (модули изображений/ответов, тумблеры §48, лимиты §26–§31). **A9 НЕ создаёт вторую административную панель** (`:5686–5689`) и **НЕ дублирует параметры** (`:5716–5717`); A9 даёт только **срез отображения** новых событий/графа через **существующий** интерфейс Эпика 1.
> **Зависимости (вход):** A8 ✅ — поставляет контракт исполнителя реакции (`react_moai(bot, chat_id, message_id, *, reaction=None, reason_code=None)`, закрытый enum 7 исходов `REACTION_*`, `REACTION_MECHANICS_ENABLED`, один call-site `set_message_reaction`; §90) + **L-1** (review T-3683); A7 ✅ — контракт решения (`action`/`target_message_id`/`reaction`/`reason_code`, `reason_code`-словарь, `silent`-short-circuit; §89); A1 ✅ — `CoordinatorDecision` (не дублировать); A2 ✅ — `ToolLoopResult`/`tool_trace`/chain-коды (§84); A3/A4 ✅ — `ImageRequest`/`run_image_request` + `image_context_memory` resolution-enum (§85/§88); A6 ✅ — `get_user_context`/`_get_user_context`/`_memory_lookup_finish` (§87); A5 ✅ — `worker_budget`/лимиты (§86). **ExecutionGraph-ядро:** `services/execution_graph_source.py` (`RunSnapshotStore` in-memory TTL 900 c / maxlen 20, `record_run`, `build_graph`, kind-enum `llm/algorithm/format/publish/other`), `web/api/analytics.py` `GET /analytics/execution/latest` (RBAC global-admin; читает PG `llm_usage_events` + in-memory snapshot), `web/static/execution_graph.js` (`fromExecution`; kind-enum уже содержит **резервный `tool`** `:48`), `web/index.html` вкладка «Аналитика» + `web/app.js` `execGraph`/fetch.
> **Baseline (Step 0 @Memory, 25.09.2026; в Step 1 НЕ перемеряется):** HEAD **`e8646af`** + **UNCOMMITTED epic-release рабочее дерево A2–A8** — A9 строится **поверх**; ничего не откатывать/не коммитить. `APP_VERSION` **2.58.30**; канон инструментов **12**; **Δ DDL = 0 (FINAL — D1:** in-memory расширение `RunSnapshotStore`; PG-таблица/DDL-санкция отклонены, R3/`threat-failure-analysis.md` **N/A****)**; **Δ каталога = 0 (FINAL — D3/D10:** счётчики `473/430/448/102/100/21`, F8 не переиздаётся**)**. Baseline-анкер = **`e8646af`**; hot-откат = env-only `AGENTIC_EVENTS_ENABLED=false`; cold = `git revert`/анкер; теги/бэкапы/`stash` не удаляются (R18).
> **Risk — `R2` ФИНАЛЬНЫЙ (D1: in-memory расширение `RunSnapshotStore`, Δ DDL=0; `threat-failure-analysis.md` — NOT_REQUIRED; финал ADR-1026-22/§13).** Обоснование R2: A9 — **аддитивные R17-safe события/узлы поверх существующего ExecutionGraph** (read-side adapter, in-memory снапшот), **fail-open, без нового пайплайна/LLM-вызова/инструмента/DDL/каталога**; blast radius ограничен диагностикой/отображением; OFF kill-switch возвращает baseline. **R3-триггеры (D12/§13): PG-таблица/DDL событий, блокирующий ввод-вывод на hot-path, утечка R17, вторая аналитика — тогда `threat-failure-analysis.md` обязателен; сейчас N/A.** Reviewer может повысить по фактическому diff.
> **Границы:** **A8-механика реакции** (§41) — **не переписывать** (A9 только **события** `REACTION_SENT`/`MESSAGE_IGNORED`); **A7-правила §44** — не переопределять; **A10** (§52–§54 приёмка эпика) — агрегатный gate; канон инструментов **12** — без нового инструмента; **нет нового LLM-вызова** (в т.ч. нет 3-го вызова); **§104 `generate_image` — no-go**; **вторую систему аналитики не создавать** (§51 `:5738–5739`); **выдуманные LLM-токены для алгоритмических операций не писать** (§51 `:5741–5742`).
> **Экземпляр-образец:** `plans/archive/telegram-reactions-round1026/tasks.md` (A8, Wave 5).

## Трассируемость (REQ → verbatim §ТЗ → блок → задачи → SC, ADR)

> **REQ-A9-01…-14** выделены из §49 (`:5638–5680`) + §51 (`:5723–5746`) + §50-границы (`:5686–5717`) + L-1 (review T-3683) + §53 (`:5846–5847`) + F0.3 `ANTI_CLICHE_*` (`backlog:311`). Состав **не сужен**; REQ не добавляется «для удобства»; все привязаны к блокам/задачам; **орфан-REQ нет**. Колонки **SC и ADR заполнены** на сверке T-3690 из `spec.md` (§2/§2.1) + ADR-1026-22; **14 REQ → 16 SC** (14 специфичных + кросс-скоупные `SC-A9-15/-16`); **orphan-REQ/SC нет**.

| REQ | Источник (verbatim, `current_task.md`) | Блок | Задачи | SC | ADR |
|---|---|---|---|---|---|
| REQ-A9-01 | §49 — 12 событий: `DECISION_START`/`DECISION_COMPLETE`/`TOOL_PLAN_CREATED`/`TOOL_CALL_START`/`TOOL_CALL_COMPLETE`/`TOOL_CALL_FAILED`/`REACTION_SENT`/`MESSAGE_IGNORED`/`IMAGE_CONTEXT_RESOLVED`/`IMAGE_GENERATION_START`/`IMAGE_GENERATION_COMPLETE`/`IMAGE_GENERATION_FAILED` (`:5638–5662`) | B | T-3691, T-3698 | **SC-A9-01** | **D2, D5, D11** |
| REQ-A9-02 | §49 — «Для каждой операции фиксировать: run_id / chat_id / message_id / action / Выбранные инструменты / Причину решения / Длительность / Ошибки.» (`:5664–5673`) | B | T-3691, T-3698 | **SC-A9-02, SC-A9-15** | **D4, D5** |
| REQ-A9-03 | §49 — «Не выводить приватное содержимое досье в публичные логи.» (`:5675–5676`) | B, G | T-3691, T-3698 | **SC-A9-03, SC-A9-15** | **D5** |
| REQ-A9-04 | §49 — «В административной диагностике показывать достаточно информации, чтобы понять, почему бот промолчал или вызвал инструмент.» (`:5678–5680`) | B, D, E | T-3691, T-3695, T-3696 | **SC-A9-04** | **D5, D9, D10** |
| REQ-A9-05 | §51 — «Использовать расширяемую ExecutionGraph из Эпика 1.» (`:5723–5724`) | C, D | T-3693, T-3695 | **SC-A9-05, SC-A9-16** | **D7, D9** |
| REQ-A9-06 | §51 — 9 реальных этапов: Decision / Memory Lookup / RAG / Web Extraction / Factcheck / Image Prompt Preparation / Image Generation / Reaction / Text Generation (`:5726–5736`) | C | T-3693, T-3698 | **SC-A9-06** | **D7** |
| REQ-A9-07 | §51 — «Не создавать вторую независимую систему аналитики инструментов.» (`:5738–5739`) | C, D, H | T-3693, T-3695, T-3701 | **SC-A9-07, SC-A9-16** | **D7, D9** |
| REQ-A9-08 | §51 — «Не записывать выдуманные LLM-токены для обычных алгоритмических операций.» (`:5741–5742`) | C | T-3694, T-3698 | **SC-A9-08, SC-A9-16** | **D8** |
| REQ-A9-09 | §51 — «Если действие завершилось молчанием, показывать результат решения без фиктивного вызова Вербализатора.» (`:5744–5746`) | C | T-3694, T-3698 | **SC-A9-09** | **D6, D8** |
| REQ-A9-10 | §50-граница — «Все новые возможности должны использовать интерфейс, созданный в Эпике 1. Не создавать отдельную административную панель.» (`:5686–5689`) | E, H | T-3696, T-3701 | **SC-A9-10, SC-A9-16** | **D10** |
| REQ-A9-11 | §50-граница — «Не дублировать один параметр в нескольких независимых формах.» (`:5716–5717`) | E, H | T-3696, T-3701 | **SC-A9-11, SC-A9-16** | **D10** |
| REQ-A9-12 | L-1 follow-up (review T-3683, A8) — `TelegramForbiddenError` (HTTP 403) должен классифицироваться как `REACTION_FORBIDDEN`, не `unknown`; поведение безопасности идентично | F | T-3697 | **SC-A9-12** | **D13** |
| REQ-A9-13 | §53 — «по логам невозможно понять, почему инструмент не сработал» (`:5846–5847`) — failure criterion, закрываемый A9 | B, G | T-3691, T-3698, T-3699 | **SC-A9-13, SC-A9-15** | **D5, D6** |
| REQ-A9-14 | F0.3 `ANTI_CLICHE_*` события (`backlog:311`; `anticliche_worker._event` существует `services/anticliche_worker.py:80`) — включить в объём A9 (закрыто Step 2: U5 → **D11**) | B, C | T-3691, T-3693 | **SC-A9-14** | **D11** |

**Кросс-скоуповые примечания:** §50 — **граница отображения** (настройки уже поставлены A4/A5/A7/A8; A9 их **не дублирует**); §41-механика A8 — **вне scope** (A9 не переписывает `setMessageReaction`/fallback/enum 7 исходов); §44-правила A7 — вне scope; §52–§54 — **A10** (агрегатный gate), кроме §53 `:5846–5847`, взятого как приёмочный ориентир; §104 `generate_image` — no-go; `CoordinatorDecision` (A1) — не дублировать. **Кросс-скоупные SC: `SC-A9-15`** (kill-switch OFF-паритет + fail-open + полный регресс; ← REQ-A9-02/-03/-13) и **`SC-A9-16`** (границы: канон 12, нет 3-го LLM-вызова, Δ DDL=0, Δ каталога=0, §104 no-go, EPIC_ONLY, R17, A8/A7 не переписаны, вторая аналитика не создана; ← REQ-A9-05/-07/-08/-10/-11). **Orphan-REQ нет** (14/14 привязаны); **orphan-SC нет**.

## Приёмочные инварианты A9 (нарушение = НЕ принято) → привязка к REQ/задачам

> **14 инвариантов**; каждый привязан к REQ из §49/§51 (+ §50-граница, L-1, §53.5846, F0.3) и **к SC** (`spec.md` §5). Потери формулировок ТЗ нет; **инварианты 1–14 → SC-A9-01…-16**.

1. **12 типов событий присутствуют:** `DECISION_START/COMPLETE`, `TOOL_PLAN_CREATED`, `TOOL_CALL_START/COMPLETE/FAILED`, `REACTION_SENT`, `MESSAGE_IGNORED`, `IMAGE_CONTEXT_RESOLVED`, `IMAGE_GENERATION_START/COMPLETE/FAILED`. **REQ-A9-01; SC-A9-01; T-3691, T-3698.**
2. **Обязательные поля на операцию:** `run_id` / `chat_id` / `message_id` / `action` / выбранные инструменты / причина решения / длительность / ошибки. **REQ-A9-02; SC-A9-02; T-3691, T-3698.**
3. **R17 — никакого приватного содержимого досье** в публичных логах/событиях. **REQ-A9-03; SC-A9-03; T-3691, T-3698.**
4. **REUSE ExecutionGraph, без второй аналитики:** события/узлы идут в **существующий** `ExecutionGraph`; второй системы аналитики инструментов нет. **REQ-A9-05/-07; SC-A9-05/-07; T-3693, T-3695, T-3701.**
5. **9 реальных этапов:** Decision / Memory Lookup / RAG / Web Extraction / Factcheck / Image Prompt Preparation / Image Generation / Reaction / Text Generation. **REQ-A9-06; SC-A9-06; T-3693, T-3698.**
6. **Без выдуманных LLM-токенов** для обычных алгоритмических операций (алгоритмический узел честно не-LLM; `null` ≠ `$0`). **REQ-A9-08; SC-A9-08; T-3694, T-3698.**
7. **silent = узел Decision без фиктивного Вербализатора** (результат решения показывается, фиктивный вызов Вербализатора не создаётся). **REQ-A9-09; SC-A9-09; T-3694, T-3698.**
8. **§50 display-only:** интерфейс Эпика 1; **никакой отдельной админ-панели**; **никакого дублирования параметров**. **REQ-A9-10/-11; SC-A9-10/-11; T-3696, T-3701.**
9. **Без нового инструмента/LLM-вызова:** канон **12** без изменений; нет 3-го LLM-вызова; JSON-схемы инструментов не трогаются; `CoordinatorDecision` (A1) — не дублировать. **SC-A9-16; T-3691, T-3693, T-3701.**
10. **L-1 forbidden-классификация:** `TelegramForbiddenError` → `REACTION_FORBIDDEN` (тот же R17-safe warning, 1 вызов, 0 текста). **REQ-A9-12; SC-A9-12; T-3697.**
11. **Whitelist payload события:** только id/числа/enum/имена инструментов/`reason_code`; **без** сырого контента досье/промптов/текста сообщений. **REQ-A9-03; SC-A9-03; T-3691, T-3698.**
12. **Kill-switch:** env-only `AGENTIC_EVENTS_ENABLED` (D3; default ON; OFF → прежнее поведение, паритет). **SC-A9-15; T-3700.**
13. **Δ каталога = 0:** счётчики без изменений (473/430/448/102/100/21); новых параметров/групп/вкладок нет (U4/D3). **SC-A9-11, SC-A9-16; T-3696, T-3700, T-3701.**
14. **EPIC_ONLY:** deployment **`DEFERRED_TO_EPIC`**; @DevOps не вызывается; **Δ DDL = 0** (D1: in-memory). **SC-A9-16; T-3703, T-3704.**

## Карта решений ADR-1026-22 → задачи

> ADR **`adr-1026-22-agentic-events-graph.md`** (T-3689, Status **Proposed → Accepted по merge**; merge — `plans/ARCHITECTURE.md` **§91** @Architect T-3703). Решения **D1–D14** (полные формулировки — ADR «Решения»); ниже — покрытие задач **T-3689…T-3705** (адаптировано на сверке T-3690). **D1–D14 присутствуют; orphan-задач нет.**

| Решение ADR-1026-22 | Предмет (U) | Задачи (блоки) |
|---|---|---|
| **D1** (U1/U3) | In-memory расширение `RunSnapshotStore`; Δ DDL=0; **финал R2** (PG-таблица/DDL отклонены) | T-3691, T-3695 (B, D) |
| **D2** (U2) | Тонкая fail-open обёртка `emit_agentic_event` над structured-logger + store; нового event-store нет | T-3691, T-3692 (B) |
| **D3** (U4) | Kill-switch `AGENTIC_EVENTS_ENABLED` (env-only, default ON); Δ каталога=0 | T-3700 (H) |
| **D4** (U6) | `run_id` = существующий `correlation_id` (S7); новый id не вводится | T-3691, T-3693 (B, C) |
| **D5** (U8) | Закрытый enum (12 §49 + 8 `ANTI_CLICHE_*` = 20) + обязательные поля + R17-whitelist | T-3691 (B) |
| **D6** (U7) | `MESSAGE_IGNORED` из silent-short-circuit A7; silent → Decision без фиктивного Вербализатора | T-3691, T-3694 (B, C) |
| **D7** (U11) | 9 этапов → существующие `kind` (+`tool`); новых kinds нет | T-3693 (C) |
| **D8** (U12) | No-fake-tokens: honest-`None` (`null` ≠ `$0`) для algorithmic/tool-узлов | T-3694 (C) |
| **D9** (U9) | Аддитивное расширение `GET /analytics/execution/latest`; нового endpoint нет | T-3695 (D) |
| **D10** (U10) | Mini App §50 — display-only срез в существующей вкладке «Аналитика» | T-3696 (E) |
| **D11** (U5) | `ANTI_CLICHE_*` (8) в enum/whitelist/kill-switch; в чат-граф **не** форсируются | T-3691, T-3693 (B, C) |
| **D12** (U13) | Границы/EPIC_ONLY/откат/pacing; финальный Risk R2 | T-3700, T-3701, T-3703 (H, J) |
| **D13** (L-1) | `TelegramForbiddenError` → `REACTION_FORBIDDEN`; поведение безопасности идентично | T-3697 (F) |
| **D14** (границы verbatim) | §49/§51/§50/§53 + A8/A7/A1/A2–A6 + канон/DDL/каталог/§104/R17/EPIC_ONLY | T-3701 (H) |

> **Обратная покрываемость (задача → решения):** T-3687→— (Step 0 baseline); T-3688→— (Step 1 planning); T-3689→D1…D14 (авторочные решения ADR); T-3690→D1…D14 (сверка, эта карта); T-3691→D1/D2/D4/D5/D6/D11; T-3692→D2; T-3693→D4/D7/D11; T-3694→D6/D8; T-3695→D1/D9; T-3696→D10; T-3697→D13; T-3698→D5/D6/D7/D8; T-3699→D5/D8; T-3700→D3/D12; T-3701→D12/D14; T-3702→D1…D14 (Reviewer gate, все решения); T-3703→D12 (merge/архивация); T-3704→D12 (DEFERRED_TO_EPIC); T-3705→D12 (handoff→A10). **Все T-3691…T-3705 присутствуют; D1–D14 полны; orphan-задач нет.**

## Санкции/вердикты A9 (финальные — ADR-1026-22 + `spec.md` §8/§13)

- **Канон инструментов:** **НЕ расширяется** — `TOOL_CALLING_TOOLS == 12`; новый инструмент/3-й LLM-вызов/JSON-схема не вводятся.
- **Δ DDL = 0** (D1): новых таблиц/колонок/индексов/PG-таблицы событий нет; SQLite **v12**; миграций нет; DDL-откат не нужен.
- **Δ каталога = 0** (D3/D10): счётчики **`473/430/448/102/100/21`** без изменений; **F8 не переиздаётся**; новых параметров/групп/вкладок нет.
- **Kill-switch:** `AGENTIC_EVENTS_ENABLED` (env-only, default ON; OFF → 0 событий/узлов, поведение и логи baseline; резолв per-call).
- **API:** аддитивное расширение **существующего** `GET /analytics/execution/latest` (RBAC global-admin, fail-open shape); **нового endpoint нет** (D9). **Новой админ-панели/вкладки нет** (D10).
- **Risk: `R2` ФИНАЛЬНЫЙ** (D1); **`threat-failure-analysis.md` — NOT_REQUIRED**; при подъёме до R3 (PG/DDL, блокирующий hot-path, R17-утечка, вторая аналитика) — обязателен.
- **R17 — обязателен:** payload-whitelist (id/enum/числа/имена инструментов/`reason_code`); никакого приватного содержимого досье/промптов/сырых текстов/ключей.
- **Release policy:** **EPIC_ONLY** → deployment **`DEFERRED_TO_EPIC`**; @DevOps не вызывается; `APP_VERSION` остаётся **2.58.30** (агрегатный bump 2.58.30 → 2.58.31 — на границе эпика).
- **Границы:** **§104 `generate_image`** — no-go; **вторая аналитика/endpoint** — запрещены; **выдуманные LLM-токены** — запрещены; `CoordinatorDecision` (A1) — не дублировать; A8-механика реакции / A7-правила §44 — не переписывать.
- **Отказной путь:** kill-switch OFF → baseline; cold — `git revert` к анкеру **`e8646af`** (+ агрегатный анкер Эпика 3); DDL-откат не нужен при Δ DDL=0.

## Блок 0 — Step 0 / baseline (T-3687)

- [ ] **T-3687 [@Memory/@Orchestrator — подтверждение Step 0]** — **Цель:** зафиксировать, что A9 стартует с anchor **`e8646af`** + **UNCOMMITTED epic-release рабочего дерева A2–A8** — НЕ трогать/не откатывать/не коммитить; baseline-числа (2.58.30; канон 12; Δ DDL≈0; Δ каталога≈0) заимствуются из Step 0 без перемера; пер-фича тега НЕТ (EPIC_ONLY). **Выход:** подтверждение в KG/`workflow_state` (машинный блок — только через `workflow_checkpoint`). **Критерий:** baseline-анкер и точка отката согласованы; незакоммиченный epic-release кандидат не затрагивается. **Зависимости:** Step 0 @Memory ✅ (факт-пак получен входом T-3688). **Статус (25.09.2026):** ✅ Step 0 факт-пак получен; перемер baseline не требуется.

## Блок A — планирование / Step 2 spec + ADR-1026-22 / сверка (T-3688…T-3690)

- [x] **T-3688 [@PM — Step 1: `tasks.md`]** — **Статус (25.09.2026):** ✅ **Выполнено:** создан `plans/features/agentic-events-graph-round1026/tasks.md`; ID-диапазон **T-3687…T-3705** (следующий свободный после T-3686 — grep `plans/` (вкл. архивы/бэкапы): T-3687+ нигде не заняты как задачи (T-3687 — только строка `next_action` в `workflow_state.md`), коллизий нет). **Цель:** разложить §49 + §51 (+ §50-граница) на верифицируемые задачи + инварианты + трассируемость; зафиксировать границу с A8 (механика реакции) и A10 (приёмка). **Выход:** этот файл. **Критерий:** REQ/инварианты/блоки согласованы; орфан-REQ нет; границы зафиксированы. **Зависимости:** T-3687.
- [x] **T-3689 [@Architect — Step 2: `spec.md` + ADR-1026-22]** — **Статус (25.09.2026): ✅ Выполнено:** созданы `spec.md` (REQ-A9-01…-14 → **SC-A9-01…-16**; 14 инвариантов; U1–U13; §4.1 handoff-карта) + **`adr-1026-22-agentic-events-graph.md`** (D1–D14; Status Proposed → Accepted по merge; ожидаемый merge §91). **Цель:** создать `spec.md` (REQ-A9-01…-14 → SC; трассировка §49/§51 + §50-граница + L-1 + §53.5846 + F0.3) + **НОВЫЙ ADR-1026-22** (**следующий свободный — verified**). Решения ADR обязаны закрыть: **(i)** персистентность/DDL (U1/U3) — in-memory (прецедент S8) vs PG-таблица, финал R2/R3; **(ii)** транспорт эмиссии (U2) — structured-logger vs новый event-store, async-safe/fail-open; **(iii)** kill-switch (U4); **(iv)** источник `run_id` (U6) — reuse `correlation_id`; **(v)** схема payload + whitelist (U8); **(vi)** маппинг `MESSAGE_IGNORED` (U7); **(vii)** 9 этапов → `kind` (U11); **(viii)** no-fake-tokens (U12); **(ix)** API-поверхность (U9); **(x)** Mini App §50-срез (U10); **(xi)** включение `ANTI_CLICHE_*` (U5); **(xii)** границы/риск/EPIC_ONLY/откат (U13). **Выход:** `spec.md` + `adr-1026-22-*.md` (Status Proposed; Accepted — по merge). **Критерий:** каждый REQ-A9 имеет SC; решения не сужают §49/§51; граница «A8 = механика / A9 = события» и «§50 = display-only» соблюдены; U1–U13 закрыты либо явно перенесены с обоснованием. **Зависимости:** T-3688.
- [x] **T-3690 [@PM — сверка]** — **Статус (25.09.2026): ✅ Выполнено — `PLANNING_CONSISTENT` выдан.** Сверка `tasks.md` ↔ `spec.md` ↔ ADR-1026-22 выполнена: заполнены **SC/ADR-колонки** (14 REQ-A9 → SC-A9-01…-16, вкл. кросс-скоупные SC-A9-15/-16; D-ссылки по темам); собрана **карта D1–D14 → T-3689…T-3705**; 14 инвариантов привязаны к SC (потерь нет); U1–U13 закрыты D-ссылками (+ соответствие handoff-тем §4.1); исправлен анкер `anticliche_worker._event:80`; зафиксированы verdicts **Δ DDL=0 / Δ каталога=0 (`473/430/448/102/100/21`, F8 не переиздаётся) / канон 12 / Risk R2 / threat N/A / kill-switch `AGENTIC_EVENTS_ENABLED` / EPIC_ONLY-DEFERRED**. **Выход:** **`PLANNING_CONSISTENT`**; расхождений не осталось; **Build разрешён (Step 3 @Builder, T-3691…).** **Критерий:** scope/исключения/risk/приёмка/зависимости/deploy/rollback согласованы; orphan-REQ/SC нет. **Зависимости:** T-3689.

## Блок B — схема событий + emission wrapper (T-3691, T-3692)

> REQ-A9-01/-02/-03/-04/-13/-14. Источник эмиссии: A1/A7 `direct_chat_service` (`CoordinatorDecision`, `reason_code`-словарь, silent/react short-circuit), A2 `tool_loop` (`ToolLoopResult`/`tool_trace`/chain-коды/`_log_degraded`), A8 `react_moai` (7-enum), A3/A4 `image_generation`/`image_context_memory`, A6 `tool_router` `_get_user_context`/`_memory_lookup_finish`, `anticliche_worker._event` (`:80`).

- [x] **T-3691 [@Builder — схема событий + payload-whitelist + R17]** — **Цель:** по решению ADR (U5/U8/D4/D5/D6/D11) ввести **схему 12+ типов событий** (§49) с обязательными полями (run_id/chat_id/message_id/action/инструменты/причина/длительность/ошибки), **whitelist payload** (id/числа/enum/имена инструментов/`reason_code`; **без** приватного содержимого досье — R17), маппингом `MESSAGE_IGNORED` из silent-short-circuit A7; **не** дублировать `CoordinatorDecision` (A1)/`ToolLoopResult` (A2). **Ссылка на код (verified):** `direct_chat_service.py` (`CoordinatorDecision`/`reason_code`-словарь/silent-short-circuit), `services/tool_loop.py` (`ToolLoopResult`/`tool_trace`/chain-коды), `services/smartmodule_utils.py` (7-enum), `services/image_generation.py`/`services/image_context_memory.py`, `services/tool_router.py` (`_get_user_context`/`_memory_lookup_finish`), `services/anticliche_worker.py:80` (`_event`). **Выход:** правки + тесты. **Критерий:** REQ-A9-01/-02/-03/-14; инварианты 1, 2, 3, 11. **Зависимости:** T-3690.
- [x] **T-3692 [@Builder — emission wrapper (async-safe / fail-open)]** — **Цель:** по решению ADR (U2/D2) ввести **тонкую обёртку эмиссии**: async-safe, fail-open (ошибка эмиссии не ломает основной поток), дешёвая, без новых LLM-вызовов; reuse существующего structured-logger/`RunSnapshotStore`-механизма. **Выход:** правки + тесты (ошибка эмиссии → основной поток продолжает). **Критерий:** инварианты 3, 9, 12; async-safe/fail-open доказаны. **Зависимости:** T-3691.

## Блок C — расширение ExecutionGraph: 9 этапов + честные метрики (T-3693, T-3694)

> REQ-A9-05/-06/-07/-08/-09/-14. Ядро — `services/execution_graph_source.py` (`RunSnapshotStore` in-memory TTL 900 c/maxlen 20, `record_run`, `build_graph`, kind-enum `llm/algorithm/format/publish/other`) + `web/static/execution_graph.js` (kind-enum `:48`, `fromExecution` `:341`).

- [x] **T-3693 [@Builder — graph kind / 9-этапное расширение]** — **Цель:** по решению ADR (U11/D7) расширить существующий ExecutionGraph так, чтобы отображались **9 реальных этапов** (Decision / Memory Lookup / RAG / Web Extraction / Factcheck / Image Prompt Preparation / Image Generation / Reaction / Text Generation) — **через существующий adapter**, без второй аналитики; маппинг этап→`kind` (`tool` уже зарезервирован `execution_graph.js:48`); учесть `ANTI_CLICHE_*` (U5/D11). **Ссылка на код:** `services/execution_graph_source.py:38–42` (kind-enum), `:73–91` (`STEP_KIND`/`STAGE_LABELS`), `:184` (`record_run`), `:485` (`build_graph`); `web/static/execution_graph.js:48,57–64,341`. **Выход:** правки + тесты. **Критерий:** REQ-A9-05/-06/-07/-14; инварианты 4, 5. **Зависимости:** T-3692.
- [x] **T-3694 [@Builder — честные метрики: no-fake-tokens + silent-no-verbalizer]** — **Цель:** по решению ADR (U12/U7/D6/D8) гарантировать: **(a)** алгоритмические узлы **не пишут выдуманные LLM-токены** (честный `null`/«Нет данных», не `$0`); **(b)** при `silent` показывается узел **Decision** без **фиктивного вызова Вербализатора**. **Ссылка на код:** `execution_graph_source.py` (honest None-not-$0; kind algorithm vs llm), silent-short-circuit A7. **Выход:** правки + тесты. **Критерий:** REQ-A9-08/-09; инварианты 6, 7. **Зависимости:** T-3693.

## Блок D — API-поверхность (T-3695)

> REQ-A9-04/-05/-07. Точка: `web/api/analytics.py` `GET /analytics/execution/latest` (`:281`, RBAC global-admin; читает PG `llm_usage_events` + in-memory snapshot).

- [x] **T-3695 [@Builder — API-поверхность событий/графа]** — **Цель:** по решению ADR (**D9**) отдать новые события/узлы через **существующий** adapter-контракт (`GET /analytics/execution/latest` — аддитивно, в тот же `nodes[]`/shape); **нового endpoint (`/analytics/agentic/latest`) не создаётся**; RBAC — существующий `requires_global_admin()`; fail-open shape — существующий; **без второй системы аналитики**; **Δ DDL = 0 (D1)**. **Ссылка на код:** `web/api/analytics.py:281` (`/analytics/execution/latest`), `:47/:53` (PG `llm_usage_events`), in-memory snapshot; `web/app.js:4335` (fetch), `:2558` (`execGraph`). **Выход:** правки + тесты. **Критерий:** REQ-A9-04/-05/-07; инварианты 4, 9, 13. **Зависимости:** T-3693.

## Блок E — Mini App §50 (display slice) (T-3696)

> REQ-A9-10/-11 + §50-граница. Точка: `web/index.html` вкладка «Аналитика» (`:2192+`), `web/app.js` `execGraph`/`execGraphApi`, `web/static/execution_graph.js`.

- [x] **T-3696 [@Builder — Mini App §50 display slice]** — **Цель:** по решению ADR (**D10**) добавить **срез отображения** новых событий/графа в **существующий** интерфейс Эпика 1 (вкладка «Аналитика»/карта вызовов; аддитивные `STEP_KIND`/`STEP_LABEL`); **никакой отдельной админ-панели** (`:5686–5689`); **никакого дублирования параметров** (`:5716–5717`); Δ каталога = 0. **Ссылка на код:** `web/index.html:2192+` (Аналитика), `web/app.js:2558` (`execGraph`)/`:4432` (`execGraphApi`), `web/static/execution_graph.js`. **Выход:** правки + JS-тесты. **Критерий:** REQ-A9-10/-11; инварианты 8, 13. **Зависимости:** T-3695.

## Блок F — L-1 follow-up: forbidden-классификация (T-3697)

> REQ-A9-12. Точка: `services/smartmodule_utils.py` — `react_moai` try/except (`:200–234`); import (`:22`) — `TelegramForbiddenError` **отсутствует**; сегодня 403 попадает в generic `except Exception` → `REACTION_UNKNOWN` (`:227–230`).

- [x] **T-3697 [@Builder — L-1: `TelegramForbiddenError` → `REACTION_FORBIDDEN`]** — **Цель (решение **D13**, REQ-A9-12):** добавить `except TelegramForbiddenError: return REACTION_FORBIDDEN` (с тем же R17-safe `_warn_reaction_failed`) **перед** generic-handler; импортировать `TelegramForbiddenError` из `aiogram.exceptions` (`:22`); **поведение безопасности не меняется** (тихий отказ, без fallback/текста/повтора) — меняется только классификация; unit-тест `TelegramForbiddenError` → `forbidden`, **1 вызов, 0 текста**. **Ссылка на код:** `services/smartmodule_utils.py:22` (import), `:213–230` (try/except), `REACTION_FORBIDDEN` (`:114`). **Выход:** правки + unit-тест (обновление `tests/test_smartmodule_utils.py` — аддитивно). **Критерий:** REQ-A9-12; инвариант 10; 0 регрессий A8. **Зависимости:** T-3690.

## Блок G — тесты (T-3698, T-3699)

- [x] **T-3698 [@Builder — тесты ядра: 12 событий, поля, R17-негатив, no-fake-tokens, silent-no-verbalizer]** — **Цель:** тесты: присутствие **12 типов событий**; обязательные поля операции; **R17-негатив** — приватное содержимое досье **не** попадает в payload/логи; **no-fake-tokens** — алгоритмический узел честно без LLM-токенов; **silent-no-verbalizer** — silent → узел Decision без фиктивного Вербализатора; 9 реальных этапов; §53 `:5846–5847` — по логам **понятно, почему инструмент не сработал**. **Выход:** новый `tests/test_agentic_events_graph_round1026.py` + прогон. **Критерий:** REQ-A9-01/-02/-03/-06/-08/-09/-13 → SC; инварианты 1, 2, 3, 5, 6, 7, 11. **Зависимости:** T-3692, T-3694, T-3697.
- [x] **T-3699 [@Builder — off-parity + регресс + adversarial]** — **Цель:** OFF-паритет (kill-switch OFF → прежнее поведение); регресс существующей аналитики/графа; adversarial: отсутствующий/битый payload, конкурентная эмиссия, большие объёмы, `message_id=None`, ошибка эмиссии (fail-open); отсутствие утечки приватного; L-1 `forbidden`. **Выход:** тесты + прогон. **Критерий:** REQ-A9-13; инварианты 3, 11, 12. **Зависимости:** T-3698.

## Блок H — kill-switch / OFF-паритет / регресс / границы (T-3700, T-3701)

- [x] **T-3700 [@Builder — kill-switch + регресс + числа]** — **Цель:** env-only kill-switch **`AGENTIC_EVENTS_ENABLED`** (решение ADR **D3**: default ON; OFF → 0 событий/узлов, прежнее поведение, паритет); полный pytest (baseline Step 0 → +N/0), JS; **канон ровно 12** без регрессий; **Δ DDL = 0** (SQLite v12; **D1** — DDL не санкционирован, R3/threat не требуются); **Δ каталога = 0** (D3; счётчики `473/430/448/102/100/21`); `APP_VERSION` **2.58.30** (без bump); `git diff --check` = 0. **Выход:** отчёт прогона. **Критерий:** 0 регрессий; OFF-паритет доказан. **Зависимости:** T-3698, T-3699.
- [x] **T-3701 [@Builder — diff-аудит границ]** — **Цель:** явная проверка границ: **вторая аналитика** — не создана (§51); **выдуманные LLM-токены** — не пишутся; **§50** — display-only, нет отдельной панели/дублирования параметров; **A8-механика реакции** — не переписана; **A7-правила §44** — не переопределены; **A10** (§52–§54) — вне diff; **A1** `CoordinatorDecision` — не дублирован; канон **12**; **§104** — no-go; `APP_VERSION` 2.58.30. **Выход:** diff-аудит-отчёт. **Критерий:** инварианты 4, 8, 9, 13. **Зависимости:** T-3700.

## Блок I — единый Reviewer gate (T-3702)

- [x] **T-3702 [@Reviewer — единый gate]** — **Статус (25.09.2026): ✅ Выполнено — Approved на 1-м цикле (обе линзы; binding Reviewed-Commit `e8646af`, Working-Tree-Hash `84d6df00…`, Spec-Hash `3f703584…`; Risk R2 подтверждён по фактическому diff; Scanner отсутствует); release-блокеров нет.** **Цель:** приёмка A9 единым Reviewer gate (Scanner **НЕ назначается** — удалён 24.09.2026): обе линзы (requirements/correctness + focused change audit), binding Reviewed-Commit/Working-Tree-Hash/Spec-Hash; проверить: REQ-A9-01…-14 покрыты, 12 событий + поля, R17 (приватное досье не в логах), REUSE ExecutionGraph без второй аналитики, 9 реальных этапов, no-fake-tokens, silent-no-verbalizer, §50 display-only без дублирования параметров, L-1 `forbidden`, канон 12, Δ DDL=0 (или санкция), Δ каталога=0, OFF-паритет; risk **R2 ФИНАЛЬНЫЙ** (D1; Reviewer может повысить/понизить по diff). **Выход:** вердикт (`review-T-3702.md`). **Критерий:** Approved или документированные release-блокеры. **Зависимости:** T-3698, T-3699, T-3700, T-3701.

## Блок J — merge / архивация / DEFERRED_TO_EPIC / handoff → A10 (T-3703…T-3705)

- [x] **T-3703 [@Architect merge + @PM архивация]** — **Статус (25.09.2026): ✅ Выполнено — @Architect merge §91 ✅ (ADR-1026-22 Accepted 25.09.2026); @PM архивация ✅ → `plans/archive/agentic-events-graph-round1026/` (5 файлов: spec, adr-1026-22, tasks, evidence, review-T-3702; SHA-256 до/после идентичны, spec `3f703584…` байт-в-байт; `threat-failure-analysis.md` отсутствует — `NOT_APPLICABLE` при R2/D1).** **Цель:** merge в `plans/ARCHITECTURE.md` (**§91** — следующий свободный после §90 A8, зафиксировано `spec.md`/ADR-1026-22) @Architect (ADR-1026-22 → Accepted); полная архивация feature-папки `plans/archive/agentic-events-graph-round1026/` @PM без потерь (spec, ADR, tasks, evidence, review; `threat-failure-analysis.md` — обязателен **только при R3**, сейчас **N/A** при R2/D1). **Критерий:** архив полон; ссылки проверены; durable-аудит A0 и архивы A0–A8 — только чтение. **Прогресс (25.09.2026): @Architect-часть ✅ — `plans/ARCHITECTURE.md` §91 добавлен, ADR-1026-22 → Accepted; @PM архивация feature-папки ✅ — `plans/archive/agentic-events-graph-round1026/` (5 файлов, SHA-256 сохранены).** **Зависимости:** T-3702.
- [x] **T-3704 = `DEFERRED_TO_EPIC`** — **Статус (25.09.2026): ✅ `DEFERRED_TO_EPIC` — A9 = accepted into pending epic release 3; НЕ `done`/НЕ `VERIFIED`/НЕ deployed; @DevOps не вызывался; агрегатный bump 2.58.30 → 2.58.31 — на границе эпика.** **Цель:** пометить A9 как **accepted into pending epic release** (deployment `DEFERRED_TO_EPIC`; НЕ «done/VERIFIED», НЕ deployed). НЕ per-фича деплой; **@DevOps не вызывается**. **Откат:** hot = env-only kill-switch OFF; cold = `git revert` к анкеру **`e8646af`**; DDL-откат не нужен при Δ DDL=0. **Зависимости:** T-3702.
- [x] **T-3705 [@PM — handoff → A10]** — **Статус (25.09.2026): ✅ Выполнено — handoff-блок «A9 handoff» добавлен в `plans/backlog.md` (после «A8 handoff»); A10 `agentic-verification` (canonical `backlog:312`; §52–§54; P0; зависит A0–A9) — ПОСЛЕДНЯЯ фича Эпика 3; агрегатный Reviewer release gate разблокирован.** **Цель:** handoff A9 → **A10 `agentic-verification`** (§52–§54; P0; зависит A0–A9): зафиксировать вход A10 (события/ExecutionGraph/Mini App-срез, kill-switch, контракты, архивы §91+), watch-items агрегатного gate, что **A9 — последняя фича перед агрегатным Reviewer release gate Эпика 3**. **Выход:** handoff-блок в `backlog.md` (**✅ выполнен на T-3705**). **Критерий:** A10 получает полный вход; агрегатный gate Эпика 3 разблокирован. **Зависимости:** T-3704.

## Вопросы U1–U13 — закрыты (вход Step 2 @Architect → решения ADR-1026-22)

> Все 13 вопросов **закрыты** решениями ADR-1026-22 (T-3689) и зафиксированы на сверке T-3690. **Канонические U-IDs — как в этой таблице (U1–U13);** соответствие handoff-темам Step 2 (Orchestrator) — в `spec.md` §4.1 (см. примечание ниже); потерь тем нет.

| U | Вопрос | Решение ADR-1026-22 (D) | Задачи |
|---|---|---|---|
| **U1** | Персистентность событий: in-memory снапшот (S8 `RunSnapshotStore`, TTL 900 c) vs PG-таблица | **In-memory расширение `RunSnapshotStore`; Δ DDL=0; финализирует R2** — **D1** | T-3691, T-3695 |
| **U2** | Транспорт эмиссии: structured-logger vs новый event-store; async-safe/fail-open | **Тонкая fail-open обёртка `emit_agentic_event` над logger + store; нового event-store нет** — **D2** | T-3691, T-3692 |
| **U3** | Нужна ли PG-таблица (санкция DDL, R3, threat-артефакт) | **Нет** (следствие D1); DDL-санкция не запрашивается; R3/threat не требуются — **D1** | T-3691, T-3695 |
| **U4** | Kill-switch: имя/скоуп | **`AGENTIC_EVENTS_ENABLED` env-only, default ON; OFF → baseline; Δ каталога=0** — **D3** | T-3700 |
| **U5** | Включение `ANTI_CLICHE_*` (F0.3; `_event` `:80`) | **Включить в enum/whitelist/kill-switch; в чат-граф не форсировать** — **D11** | T-3691, T-3693 |
| **U6** | Источник `run_id`: reuse `correlation_id` (S7) vs новый | **Reuse `correlation_id` (S7); новый идентификатор не вводится** — **D4** | T-3691, T-3693 |
| **U7** | Маппинг `MESSAGE_IGNORED` из silent-short-circuit A7 | **Эмиссия в silent-ветке Phase P; silent → узел Decision без фиктивного Вербализатора** — **D6** | T-3691, T-3694 |
| **U8** | Схема payload + whitelist; R17 | **Закрытый enum (12+8) + обязательные поля + whitelist id/enum/числа/инструменты/`reason_code`** — **D5** | T-3691 |
| **U9** | API-поверхность: расширить `GET /analytics/execution/latest` vs новый endpoint | **Аддитивное расширение существующего `/analytics/execution/latest`; нового endpoint нет** — **D9** | T-3695 |
| **U10** | Mini App §50-срез: поверхность/компонент; строго display-only | **Display-only в существующей вкладке «Аналитика»; reuse Эпика 1; без параметров** — **D10** | T-3696 |
| **U11** | Маппинг 9 этапов → `kind` | **Существующие kinds (+`tool`); `algorithm`/`tool` без токенов; Text Generation=`llm`** — **D7** | T-3693 |
| **U12** | No-fake-tokens: правило/механизм (честный `null` ≠ `$0`) | **Honest-`None`; `algorithm`/`tool` без LLM-токенов; тест** — **D8** | T-3694 |
| **U13** | Границы/риск/EPIC_ONLY/откат + pacing (A9 предшествует A10) | **R2; EPIC_ONLY/`DEFERRED_TO_EPIC`; hot=env-OFF; cold=revert `e8646af`; A9 предшествует A10 по зависимости** — **D12** | T-3700, T-3701, T-3703 |

**Соответствие handoff-тем Step 2 → канонические U (`spec.md` §4.1; потерь тем нет):** handoff-U1 «event schema» → **U8 + U1** (D5+D1); handoff-U2 «emission» → **U2** (D2); handoff-U3 «storage (DECIDES RISK)» → **U1 + U3** (D1); handoff-U4 «graph integration» → **U11** (D7); handoff-U5 «API surface» → **U9** (D9); handoff-U6 «R17» → **U8** (D5); handoff-U7 «§50 scope» → **U10** (D10); handoff-U8 «kill-switch» → **U4** (D3); handoff-U9 «first-cut scope» → **U5** (D11); handoff-U10 «L-1» → **REQ-A9-12, отдельного U нет** (D13); handoff-U11 «silence semantics» → **U7 + U12** (D6+D8); handoff-U12 «no fake tokens» → **U12** (D8); handoff-U13 «pacing» → **U13** (D12). **Расхождение нумерации handoff ↔ `tasks.md` снято явно; ни одна тема не потеряна.**

## Запреты (нарушение = НЕ принято)

- **Scanner не назначается** (удалён 24.09.2026) — только единый Reviewer gate.
- **@DevOps не вызывается** — release policy **EPIC_ONLY**, deployment `DEFERRED_TO_EPIC`.
- **Никаких коммитов** на этом шаге; **`plans/current_task.md` — immutable** (R17/R18).
- **Вторую систему аналитики не создавать** (§51 `:5738–5739`).
- **Выдуманные LLM-токены для алгоритмических операций не писать** (§51 `:5741–5742`).
- **Приватное содержимое досье — не в логи/события** (§49 `:5675–5676`; R17).
- **Никакого нового инструмента / 3-го LLM-вызова** — канон **12**.
- **§50 — display-only:** никакой отдельной админ-панели, никакого дублирования параметров.
- **§104 `generate_image` — no-go.**
- **A8-механика реакции** и **A7-правила §44** — не переписывать; `CoordinatorDecision` (A1) — не дублировать.

## Doc-maintenance (только перечень; НЕ править на этом шаге)

1. **T-3667/T-3668** — устаревшие чекбоксы в **архивном** `plans/archive/telegram-reactions-round1026/tasks.md` (статусы Step 0/Step 1 остались `[ ]` при завершённом цикле).
2. **`plans/backlog.md:314`** — смешанные маркеры порядка эпика (✅/▶️/без-маркера) — нормализовать.
3. **`plans/backlog.md:312`** — «22 сценария §52», тогда как §52 содержит **23** нумерованных сценария (`:5754–5801`) — расхождение подтверждено; исправить на 23 при ближайшем проходе.
4. **F0.3 `ANTI_CLICHE_*`** — ✅ решено (U5 → **D11**): включены в enum/whitelist/kill-switch, в чат-граф **не** форсируются; отразить в backlog/A10-входе — отдельным шагом (не сейчас).
5. **Кодовый анкер `anticliche_worker`** — ✅ исправлен на сверке T-3690: функция `_event` (`services/anticliche_worker.py:80`), не `emit_event`; в `tasks.md` расхождения устранены.
6. **U-нумерация tasks.md ↔ handoff-темы Step 2** — ✅ снята на сверке T-3690 (см. раздел U1–U13; `spec.md` §4.1); потерь тем нет.

## Кодовые анкеры (verified, для Builder/Reviewer)

- **ExecutionGraph-ядро:** `services/execution_graph_source.py` — `RunSnapshotStore` (`:109`; in-memory TTL 900 c / maxlen 20, `:118`), `record_run` (`:184`), `build_graph` (`:485`), kind-enum `llm/algorithm/format/publish/other` (`:38–42`), `STEP_KIND`/`STAGE_LABELS` (`:73–91`); честный `None`-not-`$0`.
- **API:** `web/api/analytics.py` — `GET /analytics/execution/latest` (`:281`, RBAC global-admin; PG `llm_usage_events` + in-memory snapshot).
- **UI:** `web/static/execution_graph.js` — kind-enum с резервным `tool` (`:48`), `fromExecution` (`:341`); `web/index.html` «Аналитика» (`:2192+`); `web/app.js` `execGraph` (`:2558`), fetch (`:4335`), `execGraphApi` (`:4432`).
- **Точки эмиссии:** A1/A7 `direct_chat_service.py` (`CoordinatorDecision`, `reason_code`-словарь, Phase P, silent/react short-circuit); A2 `services/tool_loop.py` (`ToolLoopResult`/`tool_trace`/chain-коды/`_log_degraded`); A8 `services/smartmodule_utils.py` (7-enum, log `:208`); A3/A4 `services/image_generation.py` + `services/image_context_memory.py` (resolution enum); A6 `services/tool_router.py` (`_get_user_context`/`_memory_lookup_finish`); `services/anticliche_worker.py:80` (`_event`, события `ANTI_CLICHE_*`).
- **L-1:** `services/smartmodule_utils.py:22` (import без `TelegramForbiddenError`), try/except `:213–230` (generic → `REACTION_UNKNOWN`).
