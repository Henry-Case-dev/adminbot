# LIVE S03 RE-PROBE — DELTA-DEPTH на проде 2.58.134 (DEPLOY-258134)

**Дата:** 26.10.2026 (прогон 15:29–15:31 UTC). **Deployed:** `076f7391a01157bad106372d405d109085a78dbc` (= reviewed `d167d686` + release-bump), healthz **2.58.134/200** (loopback + внешний).
**Назначение:** закрыть S03 (period person analysis) — единственный неудачный сценарий DELTA-DEPTH-полосы: payload обязан нести дословную инструкцию владельца §11 (`DELTA_READY_INSTRUCTION_TEXT`) ровно один раз + требование выводов по существу (`DELTA_SUBSTANCE_TEXT`), а ответ обязан быть Writer-композицией с выводами/темами/наблюдениями из найденного материала — не coverage-stub'ом (дефект r2/r3-до-фикса: ответ 125 симв. «сообщений с совпадением: 3888; метод: совпадение по префиксу…»).

## Контур (read-only, реальный LLM, ноль Telegram)

Тот же, что в r2: staging `/tmp/p0d` из deployed SHA (`git archive 076f7391`; sha-пины staging `settings.py 10073eb7567e` / `direct_chat_service.py 5add3022e464` / `direct_l1.py 4ce9c972d5b0` / `prompt_style_blocks.py 7e67090aa59a` — совпали с продом 4/4), SQLite — свежая снапшот-копия (sqlite3 backup API, 1563 MB, прод не тронут), PostgreSQL — `default_transaction_read_only=on` (probe `ro_ok:ReadOnlySQLTransactionError`), FakeBot (0 отправок в Telegram), реальный LLM `deepseek/deepseek-v4.1-flash`, hot-конфиг из PG (`wide_context_hot=true`). Драйвер r1 **байт-в-байт тот же** (`live_scenarios_12.py` sha256 `ca500edb…`, tar его не перезаписывает — файла нет в дереве репо). Обёртка `rerun_r3.py` (sha256 `fe36a233…`) — только выборка subset S03+S06 + полный захват kw-payload `_l2_write_answer` и счётчики delta-констант по 8 текстовым полям; исходник драйвера не менялся.

Прогон: boot 1.7 s → **S03 64.68 s** → S06 16.11 s, `DONE 2 scenarios`. Примечание по исполнению: первая probe-сессия отвалилась клиентским channel-read timeout (1150 s) — серверный прогон пережил разрыв и завершился сам; результаты добраны resume-сессией (та же сессия-паттерн, что в r2). На прод не влияет.

## S03 — вердикт: **PASS** (все три критерия лейна)

(a) **Payload:** `DELTA_READY_INSTRUCTION_TEXT` — **ровно 1** (`total_delta=1`), носитель — план-блок (`plan_block delta=1`; user_blocks/time_line/evidence/character/lessons/speech/style — все 0). Substance-строка `DELTA_SUBSTANCE_TEXT` — **ровно 1** там же. Предикат ожидаемо true (план `response_act=research, structure=report, extent=detailed`, 2 L1-плана medium/low). Дословный текст в plan_block подтверждён (`contains_delta_verbatim=true`, plan_block_len=1698).

(b) **Ответ — Writer-композиция с выводами по существу, не coverage-stub.** 1627 симв., 6 абзацев, 1 send. Начало (честный partial-coverage — ожидаем и допустим):

> «Слушай, Леха, тут облом: за 2022–2026 сравнить не могу, потому что в архиве, который мне доступен, лежит только кусок с 8 по 26 октября 2026. Всё остальное либо не подтянулось (таймаут), либо его просто нет. Так что честный ответ - за четыре года я тебе динамику не нарисую, могу только по свежему срезу.»

Далее — содержательный разбор доступного среза (темы/наблюдения/выводы вместо отчёта о покрытии):

> «Зато по этому срезу картина довольно плотная. Тематика. Чат сидит на двух стульях: нейронки/вайбкодинг и деньги… Даня раздаёт бизнес-лекции про монетизацию, Леха всё сводит к тому, что надо делать тривиальное дешёвое говно… Ринтаро пилит ботов и радуется, что скелет рабочий.»
> «Атмосфера. Перманентный питч-дей без инвесторов и без выручки… Плюс регулярные вбросы про железо и цены на память…»
> «Что реально изменилось - хз, сравнивать не с чем. Но если судить по тому, что есть: к 2026-му чат из болталки превратился в бесплатный бизнес-инкубатор с элементами цирка.»

Ровно контракт substance-строки: «дай лучшие наблюдения вместо отчёта о покрытии». Coverage из tool-результата (`dig_into_lore`: messages_total=3924, messages_shown=15, facts_shown=5, sampling=top_by_relevance) обработан честно — неполнота названа, наблюдения выданы. Для сравнения: до DELTA-DEPTH (2.58.133, r2) тот же сценарий отдавал coverage-stub 125 символов.

(c) **Нет подмены story и выдумок:** `lore_gate.delivery_allowed=false`, `story_delivered_as_reply=false`; similarity ответа к скомпилированной story (1954 симв.) — **0.089** (фоновый уровень); дат/цитат, которых нет в найденном материале, ответ не изобретает — вместо этого прямо отказывается фантазировать («дай мне архив за 22-25, а то я тебе сейчас нафантазирую… и это будет пиздёж»).

## S06 — sanity: **PASS**

План `answer/chat/micro, tool_policy=none`, tools=[], story не собирался. Ответ 58 симв., короткий casual, без служебной подводки/анонса: «Норм, живой пока. Ты как сам, не сдох от переизбытка идей?» Delta-инструкция и substance-строка отсутствуют во всех 8 полях payload (`total_delta=0`, `total_delta_sub=0`, predicate_expect=false) — research-only правило работает, casual payload не разрастается.

## Red flags

Блокирующих нет. Incidental (не дефекты 2.58.134): (1) `ReadOnlySQLTransactionError` traceback'и в журнале прогона — контракт PG read-only контура (fail-open telemetry), встречается во всех read-only пробах; (2) снапшот содержит фактически только 8–26.10.2026 сообщения (ретеншн/окно снапшота) — свойство снапшота, не кода; S03 на это честно указал.

## Raws (scratch, sha256)

Каталог: `OPENCODE_WORKFLOW_SCRATCH\deploy-258134\r3-results\`
- `boot.json` `0cc91ac956ce714750e78a09b24db2ddc47ff2528e9d7188a7e102112b4d5238`
- `summary.json` `7d82bac051391a3535879a3b689610da9ed75e27155df4937eddb75ae47bb776`
- `S03_period_change.json` `09dfb43c1ca10579411bceb9971b4f82d9616eaa39dc97e5ce486c351cdd7e67`
- `S03_period_change_payload.json` `e3ce86263910fd478612eca7c1d19f834e2024b50c8ab796f247d8a5effd3bdc` (полный payload с counts)
- `S06_short_everyday.json` `0c7eadc8888b3fdd9843ec5c31de3340deb06c2bd7fc3285553de46c719067ab`
- `S06_short_everyday_payload.json` `cd3acc1d82779100efa0907f03ba63b9c4b519090bf5fc43a170a93371ecc2a9`
- `run_r3.log` `b232bd4fd2c6eb4d631ee111f549da43c2e88403bc8ac9fb838f781e7d80e82c`
- Обёртка `rerun_r3.py` `fe36a233e12a913143c09a09c47029bb2a06e5a2ef20635b2be3493d9ad6034f` (загружена на сервер, sha совпал)
- Драйвер `live_scenarios_12.py` `ca500edb357bd3f7077bf236e13fbb46f417eaff910674c64f5330843ea4a96b` (байт-в-байт r1)

Деплой-факты 2.58.134 — `plans/features/asap-speech-arch/release-258134/deploy.md`.
