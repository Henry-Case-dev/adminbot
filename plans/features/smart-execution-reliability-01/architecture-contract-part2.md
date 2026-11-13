# SMART-EXECUTION-RELIABILITY-01 — архитектурный контракт, part 2

**База проверки:** production `2.58.199`, `d20a7f730715ba9e9cba7673c0557794979be339`; документ не меняет код, map или production.
**Решение:** `ARCHITECT_DECISION_ALREADY_SET`; владелец уже заморозил поведение в source stages D–M.

## D. Единый capacity contract

| Решение | Контракт |
|---|---|
| Один resolver | Единственный существующий `services.model_capacity`; один структурированный результат для L1, Writer, tool-loop, checkup, factcheck, retrieval, summary, Observer и initiative. Каждый вызов резолвит фактически назначенные `provider/base_url/route/exact model ID/alias`, не primary по умолчанию. |
| Unknown | `CHAT_UNKNOWN_MODEL_WINDOW=1_000_000`. Удалить default/exception/legacy/fallback пути `16384`; намеренно заданные реальные лимиты конкретной модели не менять. Unknown/estimated явно маркируется, не считается provider-verified и не выделяет память заранее. |
| Precedence | `provider-verified endpoint/model physical limit` > `catalog/runtime metadata` > `cached value` только того же endpoint+model+route > exact verified registry > `1M estimated/unknown`. Owner override участвует в планировании, но не превышает доказанный физический предел; конфликт показывает оба значения и причину. Не использовать family/name guessing. |
| NanoGPT | Для `z-ai/glm-5.3-flash-uncensored` использовать только существующий `_adapter_nanogpt_catalog`, точное сопоставление ID, `context_length` и `max_output_tokens`; не добавлять выдуманную registry-запись, не терять namespace/suffix и не переиспользовать cache прежней модели. Catalog miss → честный 1M estimated либо exact registry. |
| Fallback | При фактическом переходе на fallback пересобрать payload по capacity именно fallback; не занижать primary заранее. Смена provider/model/route инвалидирует связанный cache. |
| Ошибка окна | При `context length exceeded` извлечь структурированную причину, обновить endpoint/model capacity, сохранить tool evidence, пересобрать payload и выполнить ограниченное восстановление; при неизвестном лимите — адаптивное recovery с uncertainty, без возврата к 16384 и без бесконечных платных retry. |
| Разделение | `context window` — физический предел; `token budget` — существующая policy, выключаемая master budgets; `max_input`, `max_output`, `total context`, protocol overhead и минимальный output reserve — разные величины. При OFF нет скрытых секционных caps/процентного выброса нужных данных. |

**Текущая несовместимость на базе:** `config/settings.py:695` и `model_capacity.py:173–179` возвращают 16384; legacy resolver и async resolver имеют разные контуры, а `model_capacity.py:797–804` допускает developer-first режим. Builder меняет общий контракт, а не только warning.

## E. Local-first self-diagnosis

1. `SourceReader` автоматически выбирает проверенный локальный production source через `SELF_DIAG_LOCAL_REPO_ROOT` либо runtime/deploy identity; сервисный пользователь должен иметь read-доступ.
2. До чтения проверяются root, `repo_origin`, deployed/runtime version, manifest/identity, существование файла и права. Различать deployed files, checkout SHA, runtime identity и удалённый commit.
3. Порядок: (а) локальный source фактически работающей версии; (б) иной локальный snapshot с явным provenance; (в) GitHub только exact deployed commit; (г) честный partial result. Несовпадающий checkout не является production proof; `master` не подставлять.
4. Не создавать clone/index/store на запрос. Если есть только выложенные файлы без Git history, читать их в безопасном контракте, но не фабриковать SHA/manifest. Каждое evidence содержит provider/repo/commit/path/lines/verification status.

## F. GitHub/SafeFetcher

Зафиксированный отказ `SafeFetchError(destination_blocked, stage=connect, retryable=false)` локализуется только в production: DNS answers (A/AAAA), фактический peer, validated set, IPv4/IPv6, proxy/env, `httpx` transport и `network_stream`, TLS, ручные redirects и взаимодействие `GitHubProvider → SafeFetcher`. Диагностировать конкретное расхождение, не предполагать VPN/DNS причину.

Допустимый фикс: корректировать разрешённый transport/proxy handling или peer bookkeeping так, чтобы validated DNS addresses и фактический peer совпадали. Сохранить `guarded_target`, SSRF/private/link-local/metadata блокировки, peer validation, TLS verification и redirect re-validation. Запрещены trusted-by-name для `api.github.com`, shell/curl и credential logging. Публичные repo/file/symbol/branch/commit/link/related-source сценарии должны работать через существующий `SourceReader`; rate-limit/private/permission ошибки возвращаются честно.

**Нужна DevOps evidence:** один production recon с DNS/peer/transport/proxy/IPv4-6/TLS/network_stream и точным deployed effective config; без этой трассы Builder не должен угадывать исправление. Соблюдать SSH cooldown из AGENTS, HTTP `/healthz` использовать как health signal.

## H. SELF-DIAG: граница уже доказанного и остатка

2.58.199 уже доказывает подключение checkup к общему `chat_with_tools`, наличие `inspect_runtime/read_source_code`, диагностические события/счётчики и journal env/manifest identity fixes, если это подтверждено deploy evidence. Это не разрешает повторно реализовывать уже выкаченную работу.

Остаток H: (1) checkup должен объяснять причины, а не только метрики; (2) continuation должен работать семантически, без обязательных слов; (3) journal re-check выполняется от имени service user в фактическом unit; (4) после restart проверяются `.deploy/release.json`, deployed SHA и согласованность process identity; (5) unavailable/unknown не превращается в подтверждённый zero, а подтверждённый zero требует полного источника. При отказе журнала сохраняется существующий internal-event fallback.

## I. Локализация I1–I6

| ID | Локализация и минимальный ремонт | Проверка/инварианты |
|---|---|---|
| I1 | Найти конкретную DB operation/table/path/exception/schema/lock/permissions и writer transaction для meme journal; исправить первопричину и существующий spool drain. | Controlled write→temporary failure→recovery; idempotent drain, no loss/duplicate, старые записи не чистятся. |
| I2 | Трассировать fresh-stream producer, cursor scope/identity, scheduler, backlog и lag formula; чинить продвижение/обработку, не threshold. | Cursor реально движется; no rewind without processing, no loss/duplicate/skip; hidden budgets не участвуют. |
| I3 | Сопоставить LLM output → lesson/effect schema → validator для `social_preference/explicit`; решить generator-vs-validator incompatibility. | Разрешённый lesson проходит и применяется; forbidden effect остаётся rejected; не подгонять под два ID. |
| I4 | Найти producer `18d14796/4f8aced7`, синхронизировать существующий `mca_events` registry. | Canonical reason/status/secret safety; unknown не подавляется и skip не становится failure; второй registry запрещён. |
| I5 | По `asap8b01`/`qnd.event` восстановить incident cause и связь с эпиками. | Не закрывать incident искусственно, не снижать severity, не отключать detector; отдельный эпик только при доказанном самостоятельном scope. |
| I6 | Проверить VMQ/ONTO overlap прежде фикса: KNN scope должен фильтровать разрешённый chat до effective top-K; исправление 2981→800 ищется в correction-frame composer. | Не лечить `k_last=512` новым cap, не reindex без причины, не вводить char cap; полный claim или reliable continuation. Если KNN уже в VMQ — link, не duplicate; VMQ/ONTO связь: VMQ отвечает retrieval membership, ONTO — смысловую/онтологическую проекцию, совместная проверка только на seam. |

## J/K. Неподлежащие изменению границы

- LLM определяет intent, код исполняет structured decision. Никаких regex/keyword/synonym/substring/лексических fast paths, нового classifier или forced repository read; разрешены утверждённые explicit commands и технический parsing traceback/URL/symbols.
- Сохранить `diagnostic_policy`, server permissions, publication guard, SourceReader path safety, SafeFetcher, chat isolation, secret protection и side-effect idempotency. Budgets OFF не отключает безопасность; read code не даёт право менять/исполнять.
- Не создавать второй tool-loop/SourceReader/LLM client/resolver/diagnostic agent/index/log DB/fallback store/test factory; не добавлять entities, новые budget settings, миграции или платёжные изменения. Сохранить user/chat overrides, model/key/prompt и factory-on для готового исправления.

## L. Acceptance evidence и DONE

Для каждой L1–L8 trace содержит: request/correlation ID; effective settings и budget state; provider/model/route; capacity, source и confidence; реальные rounds/calls; structured tool results/errors; stop reason; фактический final payload composition (без chain-of-thought/секретов); final answer; deployed SHA. L1 проверяет >4 rounds, >6 calls и >2 calls/round как сценарий, не новый cap; L3 — NanoGPT/known-large/known-small/custom/switch/catalog miss/context exceeded; L4–L7 — local-first, GitHub security, degraded preservation, checkup continuation; L8 — причины и проверки I1–I6.

DONE только после candidate-bound independent review (implementation, trustworthy assertions, risk-driven falsification), интеграционных L1–L8, release gate и доступного production smoke. Наличие класса/настройки/зелёных unit-тестов недостаточно; mandatory техническая проверка не превращается в owner task.

## Slice decomposition и parallel safety

| Волна | Slice/assignment | Scope и зависимость |
|---|---|---|
| 0 | S0 baseline; DevOps evidence F | Read-only baseline/effective config; F evidence нужен до сетевого фикса. |
| 1 | S4 Capacity (Builder) | `config/settings.py`, `services/model_capacity.py`, capacity tests/evidence; после S1 при конфликте settings, затем shared contract для S3/S7. |
| 2 | S3 Evidence/SourceReader; S11 I6 | S3: `source_reader.py` и evidence transport; S11: `summary_memory.py`/correction path; параллельны при непересечении. S3 завершает до S5. |
| 3 | S5 Local-first → S6 GitHub | `source_reader.py` сериализовано: S5 затем S6; S6 не меняет SafeFetcher без production evidence. |
| 4 | S8 H SELF-DIAG | После S3+S5+S7; только checkup/identity/journal proof, без повторного общего tool-loop. |
| 5 | I1–I5 отдельные builders | Disjoint journal/stream/lesson/events/incident files; существующие VMQ/ONTO writers сериализуются на своих файлах. |
| 6 | S12 Reviewer | Exact integrated candidate; L1–L8, J/K, release/smoke. |

**Shared-file serialization:** `config/settings.py` (S1→S4), `services/model_capacity.py` (только S4), `source_reader.py` (S3→S5→S6), `services/direct_execution.py`/context composer (S4→S7), `services/direct_chat_service.py` (S4→S11), prompt/manifest files (один writer). Нельзя объединять кандидаты до join-barrier и нельзя запускать S12 на незамороженном capacity/evidence contract.

**SMART_PART2_READY**

### Точные Builder assignments
1. **S4:** убрать все 16384 fallback paths, внедрить precedence/metadata contract и NanoGPT exact-ID path; добавить tests для fallback recalculation и context-exceeded recovery.
2. **S3/S5/S6:** реализовать provenance-checked local-first; затем production-evidence-driven GitHub transport fix, сохранив SafeFetcher protections.
3. **S8:** проверить H residuals в service environment и связать existing evidence, не переимплементируя deployed fixes.
4. **S11:** локализовать I6 и correction frame, сначала проверить VMQ/ONTO ownership; не менять произвольные caps.
5. **I1–I5:** каждый Builder сдаёт cause/path/minimal fix/result/invariants, либо ссылку на существующий эпик с доказанным самостоятельным scope.
6. **S12 Reviewer:** независимо воспроизвести L1–L8 на одном integrated SHA и приложить поля evidence из раздела L.

Временные файлы/скретчи этой архитектурной проверки не создавались; cleanup не требуется.
