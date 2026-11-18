# Release 2.58.219 — ограничения и честные пробелы

1. **Живого хода после выката нет.** В этой сборке нет деплоя и production-
   доступа, поэтому реальный `mca07_retrieval.trace_id` и сверка SQL↔UI не
   снимались. Post-deploy проверка — агентская (runbook §3): при реальном ходе
   фиксируется `live_turn: checked`, при его отсутствии — честный
   `live_turn: no_real_turn`; статус остаётся `delivered_awaiting_evidence`,
   данные не выдумываются, владелец к QA не привлекается.
2. **Browser Use — blocked.** `BU_CDP_URL=http://127.0.0.1:9222` недоступен
   (`WinError 10061`: нет выделенного Chrome с remote-debugging). Browser Use
   не заявляется как выполненный. Визуальный контракт подтверждён:
   Playwright на точных байтах кандидата (66/66, 1280/390/320, console 0,
   overflow 0) и реальным браузером в `review-r2.md` на тех же самых
   product-байтах (1280/390/320, скриншоты).
3. **N1 (low, evidence-only).** `red-corrective-time09.json` записан как
   65 проверок/11 провалов, финальный e2e содержит 66 проверок и даёт 12
   провалов на старом UI (`status_latest_shows_current_run` добавлен позже).
   На продукт не влияет; артефакт при следующем касании обновить.
4. **N3 (nit, a11y).** При обновлении ⟳ того же хода `memoryYearCoverageLoading`
   остаётся false, поэтому `aria-busy=false` и спиннера нет; при смене
   хода/входе busy выставляется. Брифу не противоречит, но busy-семантика
   обновления того же хода неполная — backlog, не блокер.
5. **N2 (evidence-only).** `git diff --check e6239230..HEAD` даёт trailing
   whitespace в `time09/red-base-time09.txt:39` (raw-транскрипт RED).
   `git diff --check` рабочего дерева = 0; продуктовые файлы чистые.
   Одобренный evidence-артефакт не переписывался.
6. **Унаследованные границы TIME-09 (приняты ревью):**
   `period_selection` не сохраняется durable-контрактом (фильтр в API
   защитный, проверен синтетической строкой, не живым событием);
   `retrieval[]` ограничен 6 первыми по времени вызовами (для одного хода
   практически недостижимо); ходы до деплоя не имеют retrieval `trace_id`,
   поэтому UI честно показывает Writer-часть и «событий retrieval с привязкой
   нет»; Playwright использует стабы реальных payload-схем, не production-БД.
7. **Aggregate endpoint не вызывается.** `/api/memory/retrieval-coverage` =
   0 обращений в Playwright; новых endpoint/store/DDL нет, `@api_router`
   76/63 не менялся.
8. **Production effective-state не проверялся** (деплоя не было). После
   разрешённого деплоя проверяются health/version/identity/схема 48/disk,
   Playwright на выложенных байтах и живой ход по runbook; без этого VERIFIED
   не заявляется.
9. **Temp/probe-артефакты.** Все прогоны — во временном run-каталоге
   `WorkspaceData/runs/.../probe-8522a11f08`; base-reproduction worktree
   `vmq-time09-219-base-repro-...` удалён после проверки. Schema-smoke
   напечатал ожидаемые значения, но Windows заблокировал удаление temp-БД
   открытым handle; остаток (`smoke.db`, WAL/SHM) удалён вручную, на продукт
   не влияет. Секретов/ключей/прод-данных в артефактах нет.
