# ASAP2 — привязка evidence probe-r2 (остаточные строки §6)

**Лейн:** `PM-BIND-ASAP2-PROBE2`, 23.10.2026 (пятница, UTC+12).
**Источник истины строк:** `plans/features/asap2-direct-chat/source-2026-10-22.md` (§6.1–§6.3, §6.5).
**Карта:** `plans/features/asap2-direct-chat/requirements-map.json` (`candidate_commit=deployed_commit=e4ee54f3`, `strict_evidence=true`).
**Артефакты прогона** (`plans/features/asap2-direct-chat/evidence/probe-r2/`):

| Файл | sha256 | Что это |
|---|---|---|
| `results.md` | `c370da71310e6b498ca0187a58429149be37678cd0ce7feea0f65616dacbb8f4` | результаты, таблица сценариев, парафразы, ограничения |
| `protocol.md` | `f7755916a50dc3a21f3813d7c6bb7b50774387ca27be041606acdec9effc167b` | методика, изоляция, модель/sampling |
| `ledger.jsonl` | `2b0619782b5eb4b3306b62c8cd540a34b21ed8e6367e44a87becd2f371bd8e5d` | 19 вызовов, все HTTP 200 |
| `raw/*.json` | — | сырые ответы L1/L2 по каждому сценарию |

## 1. Перенос evidence в основную линию

Файлы `evidence/probe-r2/` перенесены из ветки `probe/asap2-r2-evidence` (коммит `c4c7d980`) в текущую линию
байт-в-байт (`git checkout probe/asap2-r2-evidence -- plans/features/asap2-direct-chat/evidence/probe-r2`),
хеши совпадают с зафиксированными в ветке. Код не менялся.

**`produced_on` = `e4ee54f3`.** Прогон шёл в отдельном worktree от `e4ee54f3`; код Direct Chat байт-в-байт равен
ревьюированному `34af90ff` (`git diff --stat 34af90ff e4ee54f3 -- services/direct_l1.py
services/direct_chat_service.py services/chat_prompts.py` → пусто, см. `protocol.md`). Модель прогона
`deepseek/deepseek-v4.1-flash` (nano-gpt.com) — та же, что в проде.

## 2. Что закрыто этим лейном

109 → 110 required строк (добавлена `T10-BOUNDARY`, см. §3). Итог: **87 VERIFIED / 23 PENDING / 0 READY_FOR_LIVE**.

| Строка | Было | Стало | Доказательство |
|---|---|---|---|
| `T10` (часть 1: ответ из видимой части) | PENDING | **VERIFIED** | `results.md` §2 T10 + §3: answered, clarify=false, L2 только из видимых реплик; 3 формулировки — 0 переспросов. Оговорка §5.1: явной фразы о границе нет |
| `T11` (доступный tool) | PENDING | **VERIFIED** | §2 T11: tool_use (research/fetch_url+web_search), clarify=false, в plan-блоке нет act-строки clarification |
| `T14` (reply на ролик) | PENDING | **VERIFIED** | §2 T14: tool_use (media_download+transcription), объект из reply, цель не уточняется |
| `T17` (объект в предшествующей ветке) | PENDING | **VERIFIED** | §2 T17: tool_use (transcription), цель переиспользована, переспроса нет |
| `T18` (нет инструмента для внешнего факта) | PENDING | **VERIFIED** | §2 T18b: answer/micro, clarify=false; L2 «Не знаю актуальный курс — у меня нет доступа к данным в реальном времени» |
| `T22` (новый запрос после закрытой задачи) | PENDING | **VERIFIED** | §2 T22: answer/explanation, clarify=false, 5 шагов диагностики, прежняя тема не подтянута |
| `T26` (опасное действие, неопределённость не снята) | PENDING | **VERIFIED** | §2 T26: clarification=true с target «критерий важности», одно адресное уточнение, действие не выполнено |
| `TESTS-METHOD-PARAPHRASE` | PENDING | **VERIFIED** | §3: 3 формулировки класса «понятно без деталей», 2 формулировки класса «объект неизвестен» + контраст «объект есть/нет» на T14/T17 vs P-OBJ1/P-OBJ2 |

Ложных и повторных уточнений в прогоне — **0**; `bad_repetitive_clarification` — **0**; правок кода проба не выявила,
поэтому RED/GREEN не требовался и повторный прогон после правок не нужен.

## 3. Новое расщепление: `T10-BOUNDARY` (PENDING)

Строка §6.1 #10 содержит два разных обязательства. Первое («ответ из видимой части, ничего не выдумано») доказано.
Второе («честно указать ограничение») — **нет**: в прогоне ничто не сообщало модели об усечении истории, отдельной
фразы о границе в ответе нет, и в проде evidence pack тоже не помечает неполноту (`evidence/prod-snapshot/report.md` §2).

Выделено отдельной строкой, чтобы закрытие T10 не скрыло недоказанный пункт. Решение (вариант «а» — передавать маркер
усечения в контекст + строка канона L2; вариант «б» — `not_applicable`, т.к. сигнала о границе в контракте нет, а
заставлять модель угадывать её запрещено §8.7 источника) — за `Reviewer`/`Architect`. PM строку не закрывает.

## 4. Что осталось и какой точный next_check

| Строка | Владелец | next_check |
|---|---|---|
| `T10-BOUNDARY` | Reviewer | Решить применимость пункта «явная граница истории»: вариант «а» (маркер усечения в контексте + канон L2, затем повторный T10) или «б» (`not_applicable` при текущем контракте) |
| `T20` | Reviewer | Решить, переформулировать ли T20 под новый канон (обязательный предмет) или подтвердить `not_applicable`; при новом сценарии — прогон |
| `T24` | Builder | Принять service-level тест `tests/test_asap2_clar_contract.py` (:513-546) как T24 либо добавить живой прогон после restart |
| `CLAR-L1-DIST2` | Reviewer | Сверить r2 (T10/T10a/T10b, T11, T18/T18b) с классом и закрыть или указать остаток |
| `CLAR-L1-DIST3` | Reviewer | Остаток — T20; T14/T17 покрыты r2 |
| `CLAR-L1-DIST4` | Builder | Живой прогон 2–3 парафраз ответа на уточнение (включая «сегодня» и URL) |
| `CLAR-L1-DIST5` | Reviewer | Подтвердить различение технического уточнения и живого вопроса на T22/T26 и закрыть |
| `CLAR-L1-PRINCIPLE` | Reviewer | Подтвердить принцип «можно ответить — отвечай» на полном наборе §6.1–§6.3 |
| `CLAR-L1-PRIOR` | Builder | Широкие/составные просьбы без превращения в сбор ТЗ (T04/T06/T12 уже отвечают) |
| `CLAR-L1-CONTINUATION` | Builder | T20/T24 на реальной модели (канон §4.1 уже содержит контракт продолжения) |
| `CLAR-CTX-HONEST` | Reviewer | Упирается в `T10-BOUNDARY`: «не выдумывать» доказано, «обозначить недостаток контекста» — нет |
| `CLAR-PLAN-ONETARGET` | Reviewer | Проверить класс «один адресный вопрос в Writer» вне T13/T15 (T22/T26/парафразы target) |
| `CLAR-L2-NOMENU` | Reviewer | Подтвердить отсутствие меню на r2 T10/T14 вместе с r1 T06 |
| `CLAR-L2-ROLE` | Reviewer | Подтвердить роль Writer в tool-маршрутах r2 (T11/T17/T18): писал по плану, не анкетировал |
| `TESTS-METHOD-REAL` | Builder | Остаток — T20 и T24 (полный охват §6.1–§6.3 на модели прода) |
| `TESTS-METHOD-SCREENSHOT` | Orchestrator | Приватная трассировка исходного кейса недоступна → `UNCONFIRMED`; нужна трассировка от владельца или явная фиксация границы |
| `DONE-D1` | Builder | Двухходовый прогон «вопрос бота → ответ пользователя» (видимость ветки уже подтверждена T17/T10) |
| `DONE-D5` | Reviewer | Принять plan/Writer-половину r2 (T11/T17/T18) либо запросить реальное исполнение tool-маршрута |
| `DONE-D6` | Builder | Остаток T20/T24; `needs_clarification` на проде `not_instrumented` — по телеметрии не закрыть |
| `DONE-D8` | Reviewer | Подтвердить отсутствие повторных цепочек; T22 закрыт, остаток T20/T24 |
| `DONE-REPORT` | Orchestrator | Финальный отчёт: время с зоной, prod commit/версия, изменённые точки, тесты и живые прогоны, payload, deploy/rollback/health, остаточные ограничения |
| `MIGR-PAYLOAD` | DevOps | Снять полный model payload допустимого тестового маршрута (dry-run сборка messages с effective-промптами прода, read-only) либо один оплаченный L1-вызов с ledger |
| `MIGR-HOTAPPLY` | DevOps | Hot apply в живом прод-процессе: правка промпта штатным путём с немедленным возвратом + MainPID до/после, либо service-level write→resolve с фиксацией отсутствия рестарта |

## 5. Границы этого лейна

- Лейн доказывает **семантику L1/L2** на перечисленных формулировках, а не production-телеметрию и не payload.
- Код, `plans/current_task.md`, `workflow_state.md`, прод и SSH не трогались.
- `strict_evidence=true`: каждая закрытая строка несёт `artifact_path`/`artifact_sha256` из основной линии.
- Release-гейт остаётся красным, пока открыты строки §4; EXIT и остаток приложены отделом Orchestrator.
