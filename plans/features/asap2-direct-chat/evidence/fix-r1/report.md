# ASAP2 Direct Chat — fix-r1 (блокеры 1–4 ревью `review-struct.md`)

Дата: 23.10.2026. Лейн: `ASAP2-FIX`. База: кандидат `5ad73933` (HEAD `ceba0e13`,
probe-коммит без изменений кода). Коммит этой правки — см. SHA в handoff.

Закрываются БЛОКЕРЫ 1–4 из `plans/features/asap2-direct-chat/review-struct.md`.
Блокер 5 (привязка карты) — PM; блокер 6 (`arch-audit.md`) — Architect. В этот
лейн не входят и здесь не имитируются.

## Что изменено (код)

### B1 — остаточный второй сигнал `response_act=clarification` для L2

`services/direct_l1.py:890-905` (`build_l2_plan_block`): строка
`смысловой акт ответа: clarification` теперь выводится **только** при реально
валидном уточнении — `clarification=true` (вызывающий передаёт
`bool(plan.needs_clarification)`), строгий `needs_clarification is True` и
непустой `clarification_target`. В невалидной ветке (в т.ч. `needs=false` и
`true` с пустым/пробельным target) строки нет вовсе. `target` вычисляется
один раз и переиспользуется директивой §4.3 (`services/direct_l1.py:900,946`).
Публичные сигнатуры и остальные строки плана не менялись.

RED (`evidence/fix-r1/red-b1.txt`, прогон с откатанным `services/direct_l1.py`):

```
>           assert "clarification" not in block.lower(), flag
E           AssertionError: False
E           assert 'clarification' not in '<response_p...sponse_plan>'
E               т ответа: clarification
FAILED tests/test_asap2_clar_contract.py::test_31_response_act_does_not_force_clarification
```

GREEN (`evidence/fix-r1/green-b1.txt`): `1 passed`. Расширен существующий тест
`tests/test_asap2_clar_contract.py:94-124`: отсутствие подстроки
`clarification` (в любом регистре) в блоке при `false` и при пустом target,
плюс положительная ветка (валидное `true`+target сохраняет и act-строку, и
узкую директиву §4.3). Старые утверждения теста не ослаблены.

### B2 — T33: реальный Composer/L1 ON-OFF payload

`tests/test_asap2_clar_contract.py:436-466` (Composer ON/OFF) и `:472-496`
(L1 OFF и дет. fallback). Service-level через настоящий
`DirectChatService.handle` с фейковым LLM/памятью (0 сети, 0 платных вызовов):

* L1 ON, Composer OFF: в итоговом payload (system + user) есть канон L1 и
  `[СООБЩЕНИЕ]`, нет `clarify=ask` / «задай» / «Ничего кроме вопроса» /
  «смысловой акт ответа: clarification»;
* L1 ON, Composer ON: `compose_machine_system(...).system == канон` (Core/
  Expression на машинной стадии не подключаются), payload **побайтово равен**
  OFF-варианту;
* L1 OFF: стадии `l1_planner` нет, legacy-payload чист, `<Response_Plan>` нет;
* L1-авария (невалидный JSON дважды) → дет. `fallback_plan`: L2-payload без
  `clarification`, `fallback_plan(...).needs_clarification is False`.

Старый тест T33 (fallback/speech/каноны) сохранён и переименован в
`test_33_fallback_speech_and_canons_clean` (`:160-177`) — его утверждения не
ослаблены; название больше не заявляет непокрытые режимы.

### B3 — T34: миграция/rollback/hot/кастом для новых L1/L2-ступеней

`tests/test_asap2_clar_contract.py:220-315` (`test_34_migrate_rollback_...`),
фейковый ConfigCache-контракт (`pg_available`, sync `get`, async `set`):

* `migrate_prompt_canons`: W1-байты (`PREV_DIRECT_L1_PLANNER_W1`,
  `PREV_CHAT_VERBALIZER_W1_31`) → новые каноны, ровно 2 записи категории
  `prompts`, порядок = объявление `PROMPT_MIGRATIONS`;
* повторный запуск — no-op (0 новых записей); после `rollback_prompt_canons` —
  ровно прежние байты, повторный rollback — no-op, затем ступень снова ведёт
  вперёд (стек цел);
* кастом владельца (не точное совпадение) не перетирается ни миграцией, ни
  rollback (0 записей);
* effective: `resolve_prompt`/`resolve_prompt_with_source` на hot-слое
  (ConfigCache) отдают новые каноны; `factory_text` = новые каноны
  (`reset-to-factory` не вернёт дефект); `FACTORY_SET_SHA256_12 ==
  factory_set_fingerprint() == 24ae494ac422` (не менялся — каноны в этом
  лейне не правились);
* per-chat: read-path этих stage-ключей (`resolve_prompt`) не имеет `chat_id`
  (задокументировано в `prompt_style_blocks.resolve_prompt_with_source`,
  T-3965/prompt-map-audit) — зафиксировано как **N/A с причиной**, не
  имитируется фейковым per-chat-слоем.

### B4 — T19–T24/CLAR-CTX-THREE на уровне сервиса

`tests/test_asap2_clar_contract.py:380-430` (общий драйвер
`_drive_l1`: реальный `handle`, фейковые LLM/память/БД, без сети) и тесты:

* `:513-546` второй ход: после вопроса бота короткое «сегодня» приходит в L1
  вместе с исходной просьбой (окно) и вопросом бота; L2 не получает
  `clarification`; «рестарт» (новый экземпляр сервиса + повторная загрузка
  истории) даёт **тот же** payload;
* `:552-597` ограничения: (a) усечённое окно — исходной просьбы нет и она
  **не выдумывается**; (b) бюджет контекста 140 токенов — окно сжимается,
  `[СООБЩЕНИЕ]` («сегодня») сохраняется, просьба не подмешивается;
  (c) branch (Telegram-reply на вопрос бота) доносит вопрос бота отдельно,
  даже без окна истории;
* `:603-624` первый ход: ровно один адресный вопрос по §4.3 (директива
  «недостающий обязательный предмет: period» + «Спроси только о нём»), без
  generic-опроса и без квот/счётчиков; act-строка присутствует только здесь
  (валидная ветка).

Семантика T19–T23 (правильность решения модели) остаётся за probe-лейном
(`evidence/probe/results.md`), здесь — только доставка контекста и отсутствие
второго приказа.

## Побочная находка, исправленная в этом же лейне (не блокер ревью)

`services/direct_l1.py:780-789` (`_cap_context`, шаг 4): при малом бюджете
цикл остаточного переполнения **не завершался** — `max(80, len(body)//2)` не
уменьшает блок ≤80 символов. Наблюдалось как зависание первого прогона
нового B4-теста (pytest timeout 60s внутри `build_l1_context`) при
`l1_context_tokens()=140`. Минимальный фикс: прогресс обязателен — блок,
который уже не режется (≤80 симв.), убирается целиком. Публичный контракт
деградации не менялся (структурные блоки по-прежнему неприкосновенны).

Доказательство (`evidence/fix-r1/cap-context-progress.txt`): pre-fix —
`HANG_CONFIRMED (no exit in 15s)`; post-fix — `returned in 0.17s, chars=187`,
`[СООБЩЕНИЕ]` сохранён. Существующие контракты капа не ослаблены
(`test_asap8_v6_wc_direct_d04.py` — 432 passed в широком наборе).

## Прогоны (venv py3.12, Windows, без сети и платных вызовов)

| Набор | До | После |
|---|---|---|
| Целевой (7 файлов из брифа) | 199 passed | **205 passed** (×3 подряд) |
| Широкий related (14 файлов direct/L1/L2/speech) | — | **432 passed** |

Точные логи: `evidence/fix-r1/tests-final.txt`, `evidence/fix-r1/tests-broad.txt`.
Примечание к «215 passed» из ревью: в брифе перечислены 7 путей (glob
`tests/test_asap2_*` = один файл, `tests/test_l1d_contract*.py` =
`tests/test_direct_l1_l1d_contract.py`); на них база = 199 (18 в
`test_asap2_clar_contract.py` + 181 в остальных пяти). Два дополнительных
файла из ревью не идентифицированы; ни один файл из брифа не потерял тесты
(18 → 24 в `test_asap2_clar_contract.py`, остальные 181 без изменений).
Один ранний прогон целевого набора дал одиночный transient fail
`test_asap8_initreply_binding::test_case4_transport_never_picks_addressee` с
DB-шумом `connection marked unrecoverable`; не воспроизвёлся ни standalone
(14 passed ×4), ни в трёх полных прогонах (известный async/DB-флейк-класс,
ср. примечание ревью про case7c).

## Что осталось / риски

1. **ПРЕДСУЩЕСТВУЮЩЕЕ, не этой правкой:** `tests/test_soul1_composer_parity_off.py`
   — 5 failed, 8 passed (`evidence/fix-r1/stale-dump-preexisting.txt`).
   Записанные OFF-path дампы (`direct-runtime-assembly-w1.txt`, переснятые в
   `0f3ed53a` под W1) не пересняты после смены канонов L1/L2 в `5ad73933`.
   Доказано, что не мой дифф: с откатанным `services/direct_l1.py` — те же
   `5 failed, 8 passed`. Файл вне моего WRITE_SCOPE → не правил; нужен
   re-record дампа по процедуре W1 (решение PM/Orchestrator).
   **РЕШЕНО 23.10.2026 (лейн `SOUL1-FIXTURE-RERECORD`):** дамп переснят по
   тем же код-канонам ASAP 2, дельта доказана построчно (56/56 проверок,
   только вставка §4.1/§4.2) — `plans/features/_audit-2026-10-23/
   soul1-fixtures/report.md`; целевой файл — **13 passed**. Старый
   W1-артефакт сохранён без изменений.
2. Per-chat prompt override для `prompts.direct_l1_planner_system_prompt` /
   `prompts.direct_chat_verbalizer_system_prompt` в read-path не существует —
   B3 per-chat часть закрыта как N/A с причиной.
3. Семантика реальной модели (0 ложных уточнений, T19–T23, парафразы) не
   перепроверялась платными вызовами в этом лейне: действует
   `evidence/probe/results.md` (38/45, 0 ложных) — провайдерский лимит.
   Структурные тесты не заменяют семантический прогон (§6.5).
4. Прод/PG/деплой не трогались (вне скоупа лейна); effective PG и health —
   DevOps.

## Совместимость с `arch-audit.md`

На момент работы `plans/features/asap2-direct-chat/arch-audit.md` в дереве
отсутствовал. Расхождений с B1 нет по построению: выбран самый безопасный
вариант — при невалидном уточнении противоречивый сигнал не выводится вовсе.
