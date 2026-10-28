# Review R3 — ASAP3 §2 limits (candidate `849eeed9`)

Lane: `REV-ASAP3-LIMITS-R3` · 24.10.2026 · read-only (записан только этот отчёт).
Candidate: `849eeed9` (parent `64785490`). Проверяемые пути чистые: `git status --porcelain -- services/direct_chat_service.py tests/test_asap3_hidden_limits.py plans/features/asap3-corrective/evidence/limits-inventory.md` пуст — отчёт привязан к коммиту.

## Вердикт: **PASS, блокеров нет**. HIDDEN_LIMITS/HID-* можно закрывать после привязки карты PM и зелёного `--stage review`.

## Acceptance ledger

| # | Пункт | Статус | Доказательство |
|---|---|---|---|
| 1 | Flat-ветка: WARN по `n+m>cap`; facts=10/links=5 → `0/5`; facts=5/links=10 → `5/10`; payload не изменён | **VERIFIED** | `direct_chat_service.py:8116-8122`: условие `n + m > 10`, `facts_kept=min(n,10)/n`, `links_kept=max(0,min(m,10-n))/m`. Тесты `test_persona_card_flat_branch_warns_when_facts_fill_cap` (`:301-325`, 0/5, тело 10 строк, 0 связей) и `..._links_are_cut` (`:328-349`, 5/10, 5 связей). Diff меняет только logging-блок; `lines`, заголовок и `return` не тронуты; в dossier-ветке `limit=cap+1` режется до 10 **до** форматтера при том же `ORDER BY created_at DESC, id DESC`, поэтому первые 10 строк те же. |
| 2 | Мемы: `limit=cap+1`; `10/>10` при переполнении; `10/10` без; фейк соблюдает limit; `10/15` удалено | **VERIFIED** | `direct_chat_service.py:8083-8088` (`limit=_PERSONA_MAX_ITEMS + 1`), `:8139-8144` (`memes_observed`/`memes_capped`/`memes_total_label`), `:8157-8172` (stats + WARN `%s`). Фейк `_PersonaDB.list_chat_memes` режет `[:limit]` и пишет `meme_limits` (`tests/test_asap3_hidden_limits.py:201-204`); тест переполнения: `meme_limits == [11]`, `memes_kept=10/>10` (`:236-253`); точный: `memes_kept=10/10`, `>10` отсутствует (`:276-298`). Утверждения/строки `10/15` в тестах нет; в evidence осталось только историческое «до r2» с явной пометкой недостижимости (строки 101-115). |
| 3 | Арифметика: 5+8+4+6=23; №14 только TECHNICAL; §6 п.4 уточнён | **VERIFIED** | Таблица: USER_VISIBLE — №1,2,6,8,22 (5); TECHNICAL_VISIBLE — №3,4,5,7,9,10,14,15 (8); HIDDEN_LOSS — №11,12,13,19 (4); NOT_RELEVANT — №16,17,18,20,21,23 (6); сумма 23. №14 в строке 14 и §3.4 — только `TECHNICAL_VISIBLE` (defense-in-depth), в HIDDEN_LOSS не входит. §6 п.4 (`limits-inventory.md:268-273`) уточнён: SQL-лимит связей 10, заголовок/числа = полученные строки, flat-WARN видит потерю полученного набора. |
| 4 | Числа: hidden_limits 16, затронутые 371, memory 203 | **VERIFIED** | `pytest tests/test_asap3_hidden_limits.py` → **16 passed**. 13 файлов (`add_exp_expression`, `samples_fewshot`, `dossier_irony`, `chat_lore`, `direct_chat`, `style_hint_limits`, `asap3_acceptance`, `asap3_identity_aliases`, `dossier_prompts`, `soul1_w4_sample_library`, `soul1_w4_examples_scope`, `samples_categories`, `samples_factory_persist`) → **371 passed**. Memory-набор `graphrag_memory + asap44_graphrag_batch_breaker + asap8_v63_b03_memory + asap8_v6_p1_d09_memory` → **203 passed**. Итого 16+371+203 = **590**, сходится с evidence §5. |
| 5 | Можно ли закрывать HIDDEN_LIMITS/HID-* | **YES, при условии привязки карты PM** | Содержательных блокеров не осталось: F1-R/F2-R/F3-R и арифметика r2 закрыты. Но карта сейчас не привязана: все HID-* строки `PENDING`, `evidence=[]`, `candidate_commit` пуст; `requirements_gate.py check --stage review --slice HIDDEN-LIMITS --candidate 849eeed9` ожидаемо FAIL (25 ошибок HID-*). PM должен привязать evidence и прогнать gate. Для HID-USER-SETTINGS/HID-NO-BULK-OFF/HID-NO-GLOBAL-EDITOR/HID-NO-BUDGET-BREAK одного limits-inventory недостаточно — нужны соответствующие подтверждения каталога/стиля/baseline. |

## Проверки

- Прочитаны текущий код, diff `849eeed9`, `database.py:11003-11039, 11222-11240` (факты без LIMIT; связи и мемы с `LIMIT ?`), `dossier_prompts.py:584-640`, тест-файл и evidence.
- Тесты запускались локально, без сети/прода: 16 + 371 + 203 = 590 passed, 0 failed.
- `requirements_gate.py check --stage review ...` → FAIL только по причине непривязанной карты (HID-* PENDING), не по коду.

## Findings

Блокирующих нет. Остаточные/косметические:

- **R1 (не блокер, раскрыт):** связи сверх SQL `LIMIT 10` (`database.py:11036`) неотличимы от отсутствующих: `m` — полученные строки, WARN видит только срез полученного набора. Это явно записано в §6 п.4 как отдельная микрозадача (`COUNT` в `database.py` вне write-scope полосы). r2 допускал такую запись; для закрытия HID-* PM должен явно принять этот deferral (или завести микрозадачу), не выдавая его за исправленное.
- **N1 (косметика evidence):** `memory 203` воспроизводится на 4 файлах, где `asap8_v6_p1_d09` = только `test_asap8_v6_p1_d09_memory.py`; полный набор d09 (`dream` + `deep_stages`) даёт 213. На итог 590 не влияет, но при привязке evidence лучше указать точные файлы.

## Binding

Отчёт действителен для `849eeed9` и текущего содержимого трёх проверенных путей. Любое изменение `direct_chat_service.py`, тестов или inventory требует повторной проверки затронутых пунктов.