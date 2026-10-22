# Повторное независимое ревью — asap2-direct-chat (кандидат `34af90ff`)

Дата: 23.10.2026 05:05 +12:00. Лейн: `REV-ASAP2-R2` (read-only).
Кандидат: `34af90ff` (HEAD). База для правки: `5ad73933`. Дифф фикса: `40389f55` (+ docs `a18733b5`, `34af90ff`).
Карта: `requirements-map.json` (source sha256 `8f600767…` = `source-2026-10-22.md`; 109 required-строк).
Проверены `review-struct.md`, `arch-audit.md`, `evidence/fix-r1/*`, `evidence/probe/results.md` + `protocol.md`, `source-2026-10-22.md`.

## Вердикт

**Needs Fixes.** Блокеры 1–4 из `review-struct.md` **закрыты** и подтверждены независимо (RED/GREEN на отдельных worktree, service-level тесты, прогоны). Кодовая часть кандидата технически пригодна для поезда 2.58.112. Блокируют не код, а два внешних условия:

1. **B5 (карта/evidence):** `candidate_commit` пуст, все 109 required-строк `PENDING`, evidence-строк 0; `requirements_gate.py --stage review` → EXIT 1. Пока PM не перебиндит карту, фичу нельзя объявить VERIFIED/DONE и нельзя пройти release-гейт.
2. **SOUL-1 parity:** на чистом `34af90ff` `tests/test_soul1_composer_parity_off.py` — **5 failed, 8 passed**; те же 5 падают на `5ad73933`, т.е. это не регрессия fix-r1, а следствие смены канонов ASAP2. Параллельный лейн `SOUL1-FIXTURE-RERECORD` переснял дамп в рабочем дереве (13 passed), но **не закоммитил**; поезд без этого коммита выпускать нельзя.

## Блокеры 1–4

| # | Статус | Доказательство |
|---|---|---|
| 1 — остаточный `response_act=clarification` | **закрыт** | `services/direct_l1.py:900-906`: `act_ok` требует `act != "clarification"` **или** (`bool(clarification)` ∧ `needs_clarification is True` ∧ непустой `target`). В валидной ветке `:945-954` директива §4.3 и строка act сохраняются. Независимый RED: worktree `5ad73933` + только новый тест → `test_31_...` **1 failed**, падение ровно на `assert "clarification" not in block.lower()` (`tests/test_asap2_clar_contract.py:108`). На `34af90ff` — **1 passed**. Дополнительный прямой прогон 5 сочетаний: `false`, `false+flag`, `true+empty` → строки нет; `true+target` → строка и target есть; `explanation` → act-строка есть, `clarification` нет. |
| 2 — T33 Composer/L1 ON-OFF | **закрыт** | `tests/test_asap2_clar_contract.py:388-419` (`_drive_l1` — реальный `DirectChatService.handle`, фейковые LLM/память, 0 сети), `:436-466` Composer ON/OFF (L1 payload побайтово равен по content, канон и `[СООБЩЕНИЕ]` есть, маркеров второго приказа нет), `:472-496` L1 OFF и дет. fallback. Composer-гейт реально читается в L1-пути (`services/direct_chat_service.py:4146-4152`), `compose_machine_system` не меняет system на машинной стадии. Целевой прогон — 205 passed ×3 (см. ниже). |
| 3 — T34 миграция/rollback/hot/кастом | **закрыт** | `tests/test_asap2_clar_contract.py:224-315`: fake ConfigCache-контракт (`pg_available`, sync `get`, async `set`); W1→новые каноны ровно 2 записи, порядок = `PROMPT_MIGRATIONS`; повтор — no-op; rollback → прежние байты, повтор — no-op; кастом не перетирается; hot `resolve_prompt`/`resolve_prompt_with_source` отдают новые каноны; `factory_text` — новые; `FACTORY_SET_SHA256_12 == fingerprint == 24ae494ac422`. Per-chat **N/A честно**: `services/prompt_style_blocks.py:224-243,258-279` — `resolve_prompt`/`resolve_prompt_with_source` не имеют `chat_id`, per-chat-слой для stage-ключей не читается (совпадает с `arch-audit.md` §2). Production PG/effective — отдельные MIGR-строки, не этот тест. |
| 4 — T19–T24 service-level | **закрыт** | `tests/test_asap2_clar_contract.py:513-546`: второй ход через реальный `handle` (FakeMemory с окном); в L1 payload есть исходная просьба, вопрос бота и «сегодня»; «рестарт» (новый сервис + повторная загрузка FakeMemory) даёт тот же payload; L2 без `clarification`. `:552-597`: усечённое окно не выдумывает просьбу; бюджет 140 токенов сжимает окно, `[СООБЩЕНИЕ]` остаётся; branch (`[ОТВЕТ НА (reply/цитата)]`) доносит вопрос бота. `:603-626`: первый ход — ровно одна адресная директива §4.3, act-строка только в валидной ветке. |

## Побочный фикс `_cap_context`

`services/direct_l1.py:783-787`: прогресс гарантирован — `half = len(body)//2`, при `half < 80` блок убирается целиком. Это не ослабляет защиту структурных секций: `protected = {"СООБЩЕНИЕ","УЧАСТНИКИ","ДОСТУПНЫЕ ВОЗМОЖНОСТИ","УСЛОВИЯ"}` (`:718-719`), они не выбираются victim'ом. Проверено на кандидате: при бюджетах 90/60/40/25 токенов `[СООБЩЕНИЕ]` и `[УСЛОВИЯ]` сохраняются, возврат не зависает (25 → 32 токена — protected-блоки уже не влезают, это прежний контракт «никогда не бросает»). RED подтверждён: на `5ad73933` новый `test_24_truncated_window_and_branch_are_honest` **зависает** в `_cap_context` (pytest-timeout 30 s, stack внутри `build_l1_context`), на `34af90ff` проходит. Удаление маленьких незащищённых блоков — осознанная цена прогресса; `[СООБЩЕНИЕ]`/адресный вопрос не теряются. |

## Скоуп

`40389f55` меняет только `services/direct_l1.py` (+22/−6), `tests/test_asap2_clar_contract.py` (+375/−1) и `evidence/fix-r1/*`. Новых `def`/`class`/`re.compile`/`CREATE TABLE`/квот/порогов в runtime нет; `chat_prompts.py` не менялся; `FACTORY_SET_SHA256_12 = 24ae494ac422` = `factory_set_fingerprint()`, каноны в этом лейне не правились. Остальные файлы в диапазоне `5ad73933..34af90ff` (`asap-speech-arch`, `progress_scope`, `workflow_state`) — коммиты других лейнов, не эта правка.

## Независимые прогоны (venv py3.12, Windows, без сети)

| Набор | Результат |
|---|---|
| Целевой: `test_asap2_clar_contract`, `test_asap7_direct_l1`, `test_mca08_character_speech`, `test_prompt_migrations`, `test_asap_w1_semantics`, `test_asap8_initreply_binding`, `test_direct_l1_l1d_contract` | **205 passed** ×3 (7.56 / 8.24 / 8.35 s) |
| `test_asap8_initreply_binding::test_case4_transport_never_picks_addressee` standalone | **3/3 passed** (3.71–3.77 s) |
| Широкий related (14 файлов по списку отчёта) | **402 passed** (20.87 s). Заявленные в `tests-broad.txt` 432 с этим составом не воспроизводятся (вероятно, иной набор файлов); падений 0 — на функциональность не влияет |
| `tests/test_soul1_composer_parity_off.py` на чистом `34af90ff` | **5 failed, 8 passed** (те же 5: p1, p2, p4, p5, off_path_default) |
| То же на `5ad73933` | **5 failed, 8 passed** → не регрессия fix-r1; причина — каноны ASAP2 против W1-дампа; фикс параллельного лейна в рабочем дереве даёт 13 passed, но не закоммичен |

B1 RED/GREEN: `5ad73933` + новый тест → 1 failed; `34af90ff` → 1 passed. Cap RED: timeout 30 s на `5ad73933`; GREEN на `34af90ff`.

## Семантика probe: принимаю с ограничениями

`evidence/probe/results.md`: 38/45 платных вызовов, реальные L1/L2 (`deepseek-v4-flash`), 0 ложных/повторных уточнений, 2 узких уточнения, 3 продолжения (T19/T21/T23). Это покрывает **T01–T09, T12, T13, T15, T16, T19, T21, T23, T25** и структурные T27–T31. Для инженерного DONE принимаю как лучшее доступное семантическое свидетельство при провайдерском лимите, **но не как полное §6**:

- не покрыты живьём: **T10, T11, T14, T17, T18, T20, T22, T24, T26**; T20-цепочка «период → сегодня» **not_reproduced** (4 попытки, канон больше не спрашивает период);
- по одной формулировке на сценарий, без 2–3 парафраз (TESTS-METHOD-PARAPHRASE не закрыт);
- L2 user-content упрощён (план + окно + current question), tool-маршруты не исполнялись, приватная трассировка со скриншота отсутствует (TESTS-METHOD-SCREENSHOT — UNCONFIRMED);
- прогон был на `5ad73933`, не на `34af90ff`. Перенос допустим: B1 меняет только невалидную ветку act-строки, а в probe L2-вызовах act либо валидный clarification (T13/T15), либо не clarification; L1 payload не менялся; cap 1600 токенов не срабатывал. Но это не повторный прогон на точном кандидате.

## Карта: что нельзя ставить VERIFIED

Сейчас: 145 строк всего, 109 required, **все `PENDING`**, evidence-строк **0**, `candidate_commit=""`. Формально ни одна строка не может быть VERIFIED до привязки PM. После привязки к `34af90ff`:

**Нельзя VERIFIED сейчас (нет доказательства):**
- Production/effective PG/deploy: `MIGR-INSPECT`, `MIGR-EFFECTIVE`, `MIGR-PAYLOAD`, `MIGR-BOTHSIDES`, `MIGR-DEVOPS`, `DONE-D4`, `DONE-D9` (live=True) — нужны DevOps-снимки Factory/active/effective, payload, health/rollback; `DONE-D9` — только `READY_FOR_LIVE` до деплоя.
- Нет прямого семантического/структурного эквивалента: `T10`, `T11`, `T14`, `T17`, `T18`, `T20`, `T22`, `T24`, `T26`.
- Семантические части, зависимые от непокрытых сценариев: `CLAR-L1-DIST2`, `CLAR-L1-DIST3`, `CLAR-L1-DIST4`, `CLAR-L1-DIST5`, `CLAR-L1-PRINCIPLE`, `CLAR-L1-PRIOR`, `CLAR-L1-CONTINUATION`, `CLAR-CTX-HONEST`, `CLAR-PLAN-ONETARGET`, `CLAR-L2-ROLE`, `CLAR-L2-NOMENU`, `DONE-D1`, `DONE-D5`, `DONE-D6`, `DONE-D8`.
- `TESTS-METHOD-REAL`, `TESTS-METHOD-PARAPHRASE`, `TESTS-METHOD-SCREENSHOT` — ограничения выборки выше.
- `GOV-ARCH-AUDIT` — артефакт `arch-audit.md` есть и адекватен, но **untracked**; сначала коммит, потом VERIFIED.
- `TESTS-REVIEWER` — этот `review-r2.md` может быть evidence только после коммита.
- `DONE-REPORT` — финальные commit/version/live-поля ещё не заполнены.

**Можно привязать к кандидату после коммита evidence (PM):** `CLAR-BOOL-*` (6), `CLAR-PLAN-BOUNDS/CANON/NARROW/SOURCE`, `CLAR-L1-CANON/KEYSCOPE/NEGATIVE/FLAGFALSE/SCOPE`, `CLAR-L2-CANON/ONCE`, `CLAR-SPEECH-*` (3), `GOV-*` (кроме ARCH-AUDIT до коммита), `MIGR-REVISION/OWNER/NORESET/HOTAPPLY`, `T27–T36` в структурной части (включая T31/T33/T34), `TESTS-SCOPE/UNIT/FIX`, `DONE-D2/D3/D7`, структурная часть `CLAR-CTX-THREE` и `T19–T24`.

**Кто и что делает:** PM — `candidate_commit=34af90ff`, evidence-строки с repo-relative `artifact_path` (тесты/логи/`review-r2.md`/`arch-audit.md`), `READY_FOR_LIVE` только для D9 и deploy-only строк с конкретной postdeploy-проверкой и rollback; semantic/production — не VERIFIED без доказательств. Builder/parallel lane — закоммитить пересъёмку SOUL-1-фикстур. DevOps — MIGR/PG/health/rollback, затем `--stage release`. Карту я не правил.

## Поезд 2.58.112

**Код `34af90ff` можно включать в поезд как код** (блокеры 1–4 закрыты, целевой набор зелёный, scope чистый), при трёх условиях:

1. PM перебиндит карту/evidence до release-гейта; сейчас `--stage review` = EXIT 1, release-гейт также не пройдёт.
2. Поезд включает **закоммиченный** коммит пересъёмки SOUL-1-фикстур; чистый `34af90ff` без него даёт 5 red parity-тестов.
3. DevOps после деплоя снимет effective PG/payload/health/rollback и закроет D9; до этого фича не DONE.

Если поезд требует зелёный review-гейт **до** деплоя — кандидат пока включать нельзя (только после B5).

## Incidental

- `evidence/fix-r1/candidate.txt` содержит «see hashes above», но хешей в файле нет; сообщение `a18733b5` заявляет привязку sha256, которой артефакт не подтверждает. PM должен привязать карту к фактическому коммиту `34af90ff` и artifact sha256, а не к этой заметке.
- `evidence/probe/results.md:66` и `structural.json` (T31/T31b) фиксируют PASS на `5ad73933`, где act-строка ещё была; это исторический артефакт, **не доказательство B1**. Доказательство — новый тест на `34af90ff`.
- `services/direct_chat_service.py:2779-2781` — мёртвая telemetry-ветка `clarify == CLARIFY_ASK` (из прошлого ревью), безвредна.
- `arch-audit.md` и `review-struct.md` untracked; до коммита evidence-привязка к ним невозможна.
- `tests/test_asap7_direct_settings.py` (2 pre-existing fail, user_version 35 vs 37) в мой широкий набор не входил; это не регрессия кандидата.

## Проверки/источники

- Код/тесты: `git show 40389f55`, `git diff 5ad73933..34af90ff`, текущие `services/direct_l1.py`, `services/direct_chat_service.py`, `services/prompt_style_blocks.py`, `services/prompt_migrations.py`, `tests/test_asap2_clar_contract.py`, `tests/test_soul1_composer_parity_off.py`.
- Worktree `5ad73933` + только новый тест (RED), worktree `34af90ff` (чистый, parity). Worktree удалены после проверки.
- Гейты: `--stage plan` EXIT 0; `--stage review --slice CLAR-PLAN --candidate 34af90ff` EXIT 1 (candidate mismatch + 5 mandatory PENDING).
- Внешние источники не требовались: решение repo-local, версионных внешних контрактов нет.
