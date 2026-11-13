# Независимое ревью: SELF-DIAG-01 corrective core (candidate `76fcb829`)

> **Происхождение записи.** Вердикт вынесен независимым Reviewer в отдельной сессии и
> передан Orchestrator 2026-11-13 по точному кандидату ниже. Ветка `self-diag/corrective`
> не содержала отдельного reviewer-файла на момент привязки карты, поэтому PM
> фиксирует вердикт дословно по существу (состав проверок, вердикт, границы), не
> добавляя собственных выводов. Reviewer может заменить этот файл своим
> авторским артефактом — карта перепривяжется на него без изменения строк.

## Область и привязка
- Code+tests candidate: `76fcb82962592a8e099239cd11e6c34ff13cf407`.
- Docs candidate: `e5a92ebae08dd312ec739a94c12c76e7ddcbef3d` (per-case semantic hashes, stage-gate source bytes).
- Base: `234776589c934024ed0e8dceba189fb9d70d3215` (2.58.198).
- Branch/worktree: `self-diag/corrective`.
- Источники требований: owner input `plans/owner_inputs/2026-11-13-selfdiag-corrective-journal-code-identity.md` §§1–9; контракт `corrective-2026-11-13/architecture-corrective.md`.
- Scope ревью: product-путь «входное сообщение → L1 → структурированное решение → tool loop → повторная модель → публикация/ответ», anti-hardcode инвариант, A–G traces, семантическая обобщаемость. Вне scope: deploy identity/счётчики (свой slice), production Telegram/journal-through-checkup (postdeploy), закрытие всего SELF-DIAG-01.

## Ledger проверенных поведений
| Поведение | Итог | Основание в артефактах |
|---|---|---|
| Реальный чекап исполняет существующий tool-loop (bundle + объявленные tool schemas), результаты возвращаются той же модели | VERIFIED (candidate) | `ag-traces-76fcb829.json` B: `CheckupService.checkup -> tool_loop.chat_with_tools -> ToolRouter`, реальные `read_source_code` + `inspect_runtime`, `result_source.status=ok/verified=true`, финальная синтезация. |
| Структурированное решение `diagnostic_research` вместо лексического определения намерения | VERIFIED (candidate) | `services/direct_l1.py`: закрытые enum/normalize, `needed=false`/`unknown` не запускает инструмент; `DIAGNOSTIC_SOURCE_CAPABILITY` — исполнение решения, не маппинг слов; тесты corrective (28). |
| Продолжение после отчёта доходит до L2 Writer и отправленного ответа, без запроса ссылки на собственный репозиторий | VERIFIED (candidate, Writer/send boundary) | `ag-traces-76fcb829.json` C: реальные `mca_bot_outputs(output_kind=checkup_report)` + `DirectChatService.handle` + adaptive tool phase + Writer + send; финальный ответ по прочитанному коду, `no_repo_request=true`, `writer_input_has_code=true`; steps `l1_planner, orchestrator, orchestrator, l2_writer`. |
| Найден и исправлен реальный дефект причинной цепочки | VERIFIED | typed decision форсировал `execution_mode="adaptive"`, канон — `adaptive_tool_chain`; `resolve_execution_mode` понижал до `simple_tools`, orchestrator не вызывался, L2 не получал код. Исправлено на `_dx.EXECUTION_ADAPTIVE`; тест проверяет resolved mode, не строку. |
| Пустой L1 (`LLMBadResponseError: empty content`) не теряет установленное намерение, но и не запускает инструменты сам | VERIFIED (candidate) | `ag-traces-76fcb829.json` D: `plan=None`, сохранено предыдущее решение только для reply-to-bot, `preserved=true`, автоматического tool call нет. |
| Недоступный журнал/источник даёт `unavailable`/`not_checked`, а не ноль | VERIFIED (candidate) | `ag-traces-76fcb829.json` E: `status=unavailable`, `logs_read_failed`, `journal_window` not_checked, `facts={}`. |
| Негативный RBAC: участник не получает закрытые данные | VERIFIED (candidate) | `ag-traces-76fcb829.json` F: `denied=true`, `handler_calls=0`, отказ без содержимого. |
| Identity различает manifest/checkout и не выдаёт checkout за deployed | VERIFIED (candidate, локально) | `ag-traces-76fcb829.json` G: manifest `ffff…` vs checkout, `deployed_matches_checkout=false`, `local_checkout_unverified`. Production-манифест — отдельный slice. |
| Байты owner-промпта/личности не изменены; P4-контракт исправлен | VERIFIED | system payload байт-идентичен записанному канону после `_canon_patch`; user payload содержит ровно один `[ДИАГНОСТИЧЕСКОЕ РЕШЕНИЕ]` и `DIRECT_L1_DIAGNOSTIC_RESEARCH_ADDENDUM.strip()`; тест P4 зелёный. |
| Семантическая обобщаемость на незнакомых формулировках | VERIFIED (локальный провайдер) | `semantic-live-76fcb829.json`: 2 серии × 9 кейсов, 4/4 positives → `needed=true,target=self` + реальный `read_source_code` `ok`, 5/5 negatives → `needed=false`, 0 tool calls; один честный флип `neg_external` только в `target` (`null`/`unknown`), исход не менялся. Не production-эквивалент. |
| Anti-hardcode инвариант | VERIFIED по фактическому пути | Reviewer лично проследил маршрут сообщение+canonical/reply/context → L1 вход/схема → структурированное решение → capability/tool resolution → Router guard/RBAC → реальный tool call → результат → повторная модель → publication/output guard → ответ; ветви обычный checkup, continuation, self/external и L1 пустой/недоступный. Механический скан `anti-hardcode-audit-76fcb829.md` — вспомогательный, не замена. |

## Три независимые опоры
- **Implementation:** прочитаны изменённые точки исполнения (`services/checkup_service.py`, `handlers/checkup.py`, `services/direct_chat_service.py`, `services/direct_l1.py`, `services/tool_router.py`, `services/source_reader.py`, `services/chat_prompts.py`, `services/checkup_prompts.py`, `services/direct_capabilities.py`) и их вызывающие; поведение соответствует контракту, второго SourceReader/агента/LLM-клиента/pipeline не добавлено.
- **Test validity:** прочитаны assertions corrective-наборов; они проверяют наблюдаемые значения/состояния (dispatch, resolved mode, Writer input, отправленный ответ, статусы источников, deny/handler_calls), а не тавтологии и не «наличие класса». Моки провайдера допустимы как fixture текста; реальные БД/роутер/Writer/send участвуют. Прогоны: 28 passed (новый), 330 passed (focused), 442 passed (L1/engine), p4 1 passed; 4 старых падения воспроизведены по одному на базе `23477658` (pre-existing, вне scope).
- **Independent falsification:** Reviewer самостоятельно выбрал adversarial-формулировки (положительные без маркеров, похожая лексика с иным намерением, внешний проект, цитата чужой просьбы, обычное продолжение, просьба объяснить уже полученное) и прогнал фактический путь; проверено, что решение принимает модель, а не слова. Проверен и негативный сценарий пустого L1.

## Границы вердикта
- **Approved** для predeploy corrective slice — только перечисленная область и точный candidate выше; это не deployment/release acceptance и не DONE родительского SELF-DIAG-01.
- Остаются postdeploy (README_FOR_LIVE, не VERIFIED): реальный production-чекап с чтением journald текущего invocation; production Telegram-ответ и continuation без просьбы о ссылке; production manifest/effective identity; production smoke.
- Локальный live-model прогон использует проектный локальный провайдер, а не production route/model/context; journal локально — fixture на границе subprocess.
- Четыре pre-existing падения (evol018-аудит ×2, addtr лоадер, P4 до правки) остаются вне scope; P4 закрыт контрактной правкой.
