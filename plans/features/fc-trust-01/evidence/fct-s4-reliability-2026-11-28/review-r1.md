# FCT-S4 (FCT-1001/FCT-1002) — независимое ревью r1 (Reviewer, 28.11.2026)

- Роль: независимый Reviewer. Продукт, тесты, карта и ветка не менялись.
- Репозиторий/worktree: `C:\Users\main\.config\opencode\WorkspaceData\worktrees\c742e4de9e92c489\fc-trust-s4-reliability-4488c81af065-d034fef8`
- База: `fa4ba6292` (release/2.58.272). Кандидат кода: `dc6703a8f77b11505f3fe8518960fadc9df806de`.
  Tip `585240d0d` — evidence-only поверх кандидата (`git diff dc6703a8f 585240d0d` = 9 файлов evidence).
- Worktree на входе чистый (`git status --porcelain` пусто, HEAD `585240d0d`). Единственный новый файл после ревью — этот артефакт.
- Границы подтверждены диффом `git diff fa4ba6292 dc6703a8f`: только `handlers/factcheck.py`,
  `services/persistent_throttling.py`, `services/smartmodule_throttling.py`, 4 тестовых шва и evidence.
  `services/search_aggregator.py`, `services/temporal_factcheck.py`, `services/prompt_registry.py`,
  рендер, DDL, флаги, инструкции LLM не изменены.

## VERDICT: APPROVED_FOR_RELEASE_PREPARATION

Деплой/прод не выполнялись и не заявляются. Живой Telegram/провайдерский прогон не выполнялся.

## Покрытое поведение и независимые доказательства

| Проверка | Команда / способ | Результат |
|---|---|---|
| Новые тесты на кандидате | `pytest tests/test_fc_trust_s4_reliability.py -q -p no:cacheprovider` | **11 passed** (5.07 s) |
| RED на чистой базе | временный detached-worktree `fa4ba6292` + тот же новый файл | **2 failed, 9 passed**; падают ровно отмена (`assert 300.0 == 0`) и single-flight (`assert 2 == 1`), остальные 9 — контроль |
| Широкий профиль фактчека/троттлинга на кандидате | `test_factcheck_media_2026_10_25, test_rc_target_media_evidence, test_mca20_integration_round1045, test_persistent_throttling, test_evol_fc_admission, test_fc_trust_{verdict,target,retrieval}, test_fc_trust_s4_reliability` | **298 passed, 1 failed**; единственный провал `test_insufficient_evidence_is_not_no_claim` воспроизведён на базе `fa4ba6292` тем же тестом (предсуществующий, вне линии) |
| `PersistentCooldownTracker.claim` — чтение+занятие в одной `write_transaction` | чтение кода (`services/persistent_throttling.py:158-190`), `DatabaseService.write_transaction` держит `_single_writer` на всю транзакцию (services/database.py:2741+) | атомарно в пределах процесса; на базе окно `remaining()`→`touch()` подтверждено RED-тестом |
| Отмена handler'а | чтение wrapper'а (`handlers/factcheck.py:1200-1215`), `_ACTIVE_SLOT` ContextVar, `_settle_cancelled`/`_refund_cooldown`; прогон с реальным `PersistentCooldownTracker` на `DatabaseService` | отмена: `remaining 299.8 → 0.0`, незавершённых задач 0; вердикт: `remaining 300.0` (слот сохранён); `CancelledError` пробрасывается |
| Пути выхода | success/error/timeout/cancel: `except Exception` (не `BaseException`) в handler/service/orchestrator, `create_task` в фактчек-пути отсутствует — отмена не глотается и задач не порождает | подтверждено |
| Повторный settle | прямой вызов `_settle_cooldown` дважды | `kept:verdict` → слот снят; два `refund:error` → повторный DELETE идемпотентен, двойного списания/возврата нет |
| Изоляция FCT-1002 | 4 новых теста + существующий `test_fc_trust_verdict.py::TestFCT1002ConcurrentChatsIsolation` | зелёные; продукт для FCT-1002 не менялся — это характеризация существующего контракта |

## Свои мутации (scratch-worktree на `dc6703a8f`, после каждой файл восстановлен)

| ID | Мутация | Ожидание/факт |
|---|---|---|
| R-FCT1001-SPLIT-HANDLER | handler снова `remaining()`+`touch()` | RED (single-flight) |
| R-FCT1001-CLAIM-ALWAYS | `claim` игнорирует занятую строку | RED (single-flight) |
| R-FCT1001-CANCEL-NOREFUND | wrapper не снимает слот при отмене | RED (cancel/refund) |
| R-FCT1002-CACHE-CHATID | `chat_id` убран из ключа кэша среза | RED (cache isolation) |
| R-FCT1002-EGRESS-REFS | `evidence_refs` дописаны в публикуемый текст | RED (egress) |
| R-FCT1002-MIX-REPLACE | общий coverage подменяет coverage прогона | RED (roles) |
| R-FCT1002-MIX-ACCUM | coverage накапливается между прогонами | новый roles-тест **GREEN** (см. REV-FCT-S4-04), но существующий `test_two_chats_concurrently_do_not_share_evidence_or_parts` **RED** → комбинированный набор ловит |
| R-FCT1001-SETTLE-KEEPSLOT | `_settle_cooldown` не снимает `_ACTIVE_SLOT` | 11 passed (см. REV-FCT-S4-03) |

## Findings

### REV-FCT-S4-01 — LOW, IN_SCOPE, не блокирует
**Ожидалось:** после подтверждённой доставки вердикта отмена не возвращает пользовательский слот
(так утверждает и комментарий `handlers/factcheck.py:639-641`, и `implementation.md` §3).
**Факт (прогон):** legacy-путь: доставка (`send_chunked_reply`), затем `await record_factcheck_output`;
отмена в этом окне → `delivered=1, remaining=0.0` (слот возвращён). В v2/temporal тот же разрыв
по коду: `deliver_factcheck` (`services/factcheck_orchestrator.py:2001`) → awaits ledger/`record_delivery_stage`/
`_emit_claim_coverage` → только потом `_settle_cooldown` (`handlers/factcheck.py:1450`); отмена между ними
вернёт слот (прогоном не исполнялось, путь тот же).
**Влияние:** редкая гонка при отмене задачи (напр. shutdown) даёт пользователю один лишний фактчек в окне
кулдауна. Не двойной расход, не утечка, не потеря доставки; текст линии FCT-1001 («ранние/технические
отказы не расходуют лимит без причины») не нарушается.
**Рекомендация:** либо принять как известное ограничение и поправить формулировку в evidence
(«после `_settle_cooldown`, а не после доставки»), либо снимать `_ACTIVE_SLOT` сразу после подтверждённой
отправки в legacy-пути и завести отдельный тест «delivered-then-cancel». Не блокер релиза.

### REV-FCT-S4-02 — LOW, BACKLOG
`PersistentCooldownTracker.claim` атомарен только в пределах одного процесса (single-writer lock).
Проба с двумя `DatabaseService` на одном файле (два соединения, барьер на `SELECT last_ts`):
`A=(True,0.0) B=(True,0.0)` — при межпроцессном interleaving оба занимают слот; docstring модуля
(«несколько процессов … делят один слот») и модульное правило «SELECT-then-UPDATE запрещён» для
`claim` строже, чем реализация. Прод — один systemd-процесс, поэтому требование «два одновременных
запроса» выполнено; актуально только при будущем multi-worker. Follow-up: одиночный условный UPSERT
с `WHERE`/`RETURNING` либо `BEGIN IMMEDIATE`.

### REV-FCT-S4-03 — INFO, BACKLOG
Строка `_ACTIVE_SLOT.set(None)` в `_settle_cooldown` не покрыта тестами (мутация R-FCT1001-SETTLE-KEEPSLOT
остаётся зелёной). Для достижимых путей поведение не меняет (после `_settle_cooldown` нет await-точек до
возврата; повторный refund идемпотентен), влияет только на телеметрию при отмене во время самого refund.
Тест на «settle → отмена/повторный settle не даёт второго возврата» желателен, не обязателен.

### REV-FCT-S4-04 — INFO, BACKLOG
1) Новый `test_roles_and_sources_do_not_mix_between_chats` проверяет только `parts[0]` и `evidence_rows`,
поэтому «чужая» дополнительная part (накопленный coverage) им не ловится — ловится существующим
`test_two_chats_concurrently_do_not_share_evidence_or_parts` (проверяет конкатенацию всех parts).
Комбинированно контракт закрыт; для локальной независимости нового теста стоит добавить проверку
всех parts. 2) `test_cancel_before_slot_is_claimed_keeps_no_state` назван про отмену до занятия слота,
но отмену не выполняет (это путь «цели нет»); отдельной отмены до claim нет — поведение тривиально
(`_ACTIVE_SLOT` ещё None), но имя теста вводит в заблуждение.

## Ограничения ревью
- Не выполнялись: живой Telegram, реальные LLM/embedding-провайдеры, деплой/прод, multi-worker.
- RED/GREEN и мутации воспроизведены на Python 3.12 (venv `C:\Code\Python\adminbot\.venv`), cwd — соответствующий worktree, `-p no:cacheprovider`.
- Временные проверочные worktree (`fa4ba6292`, `dc6703a8f`) и скрипты вне репозитория удалены; клон кандидата не изменён.

## Рекомендация по статусам (без правки карты)
- **FCT-1001 → VERIFIED.** Текст линии выполнен: single-flight на прод-дефолте персистентного трекера
  (single-process) и возврат слота при отмене подтверждены RED→GREEN и собственными мутациями;
  ранние/технические отказы не расходуют лимит, успешный вердикт расходует (кроме узкой гонки REV-FCT-S4-01,
  зафиксированной как известное ограничение вне acceptance-текста линии).
- **FCT-1002 → VERIFIED.** Продукт не менялся; изоляция ролей/источников/кэша срезов/egress подтверждена
  собственными мутациями (cache/egress/coverage-replace RED), остаточные пробелы тестов — REV-FCT-S4-04.