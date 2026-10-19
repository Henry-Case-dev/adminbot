# F4 pre-registration — live behavioural acceptance of ADD-EXP F1 (prod 2.58.97)

Recorded **before** the live wave (harness `accept97_live.py` sha256_12 below).
Purpose: the pass/fail bounds and the probe set are fixed in advance, so the
result cannot be re-interpreted after seeing the answers.

## Candidate / environment

- Prod: **2.58.97** @ `99f5672c` (deploy T0 2026-10-19 19:13:31Z, PID 3791730).
- Canon under test: `5b86517e` (`services/mca_expression.py`,
  `PROFANITY_INSTRUCTIONS["frequent"|"occasional"|"off"]`).
- Chats: A `-1002661910336` (waves), B `-1004482340693` (off isolation).
- Temporary state: only chat-scope `character.expression.profanity`; restored
  to the pre-run state afterwards (per-chat key set + document compared).

## Pre-registered bounds

| Mode | Probes | PASS | FAIL |
|---|---|---|---|
| `frequent` | 6 conversational, 3 contexts × 2 | **≥3 of 6** replies with ≥1 own profanity root **and** roots present in **all 3** contexts **and** ≤1 root per sentence | <3/6, any context without mat, or >1 root in a sentence |
| `occasional` | 10 conversational | **1..5 of 10** (widened bound; nominal canon “1 in 4–5”) | 0/10 (inert) or >5/10 (too frequent) |
| `off` | 2 conversational + 1 quote | 0 own mat in 2 replies; quoted mat reproduced verbatim, no distortion | any own mat; quote altered/missing |
| genre summary (inside `frequent`) | 1 | facts `2.58.97 / 71 / 940 / 6` intact, 0 own mat | any fact lost or mat forced |
| wire | all L2 calls | `<Expression_Settings>` + exact mode line + exact rendered layer text | marker/mode/text missing |
| postprocess | all turns | raw L2 output == delivered text | silent trimming/injection |
| few-shot | all composes/wire | `<Expression_Examples>` = 0 (drafts `owner_approved=0`) | block appears without owner approval |

Diagnostics are not masked: if `frequent` fails while the policy is in the
payload and raw == delivered, the class is `model_ignored_instruction`
(`emit_expression_diag`); provider refusal / postprocess / non-injection are
distinguished by their own evidence.

## Probe set (disjoint from few-shot drafts and acceptance-96 phrases)

`frequent` (3 contexts × 2):
1. banter — «бот, ты вчера так уверенно советовал сменить тариф, что я почти
   поверил, будто ты из техподдержки»
2. banter — «бот, три абзаца про пользу утренних прогулок — это ты серьёзно?
   Сам, поди, до обеда спишь»
3. argument — «бот, не согласен: твой вариант с кэшем только всё усложнит, у
   меня и без него в проде нормально»
4. argument (бытовая жалоба) — «бот, стиралка второй день гудит на отжиме,
   вызывать мастера или подождать»
5. joke/short (шутка) — «бот, пошути про то, как я в третий раз переписываю
   один и тот же отчёт»
6. joke/short (короткий ответ) — «бот, ты вообще выспался?»
7. genre summary — «бот, тех-сводка в две строки: прод 2.58.97, диск 71%,
   ОЗУ 940 МБ, аптайм 6 суток»

`off` (B):
1. banter — «бот, у нас в чате спорят, кто виноват в сломанном билде — я или
   сеньор. Рассуди по-честному»
2. short — «бот, как думаешь, стоит ли мне идти на эту встречу в субботу?»
3. genre quote — «бот, Петя просил передать слово в слово: «ну и хуйня этот
   ваш рефакторинг, я устал» — ничего не правь»

`occasional` (A, 10): сосед сверлит; пароль от вайфая; дедлайн перенесли;
ужин из курицы и риса; резко ответил коллеге; кот скинул кружку; ноутбук
греется; удалёнка vs офис; погода в Москве на выходных; третий раз
перечитываю совет.

Disjointness machine check (`disjoint-check.json`): no shared 3-gram with the
12 few-shot `input_text` drafts or the acceptance-96 phrases; max token
Jaccard 0.286 (single shared short token, no shared phrase).

## Harness fingerprint

- `accept97_live.py`, `accept97_base.py` (proven ACCEPTANCE-91…96 bootstrap,
  labels/paths retargeted), `accept97_clean.py`, `accept97_journal.sh`,
  `run_accept97.py` — sha256 recorded at upload (`VERIFY_UPLOAD` in the run log).
- Criteria math proven offline before the run: scanner/criteria self-test
  (GREEN matrix PASS, RED matrices FAIL, root-per-sentence violation blocks
  PASS) — `harness/_selftest_97.py` output in the run README.
