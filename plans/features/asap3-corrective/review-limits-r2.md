# Review R2B — ASAP3 §2 limits (5 HIDDEN_LOSS)

Lane: `REV-ASAP3-LIMITS-R2B` · 24.10.2026 · read-only.

Candidate: `64785490` (HEAD). Проверяемые файлы идентичны `e6c9b65b`:
`git diff --stat e6c9b65b..HEAD -- services/direct_chat_service.py services/dossier_prompts.py services/mca_expression.py services/mca_sample_library.py services/summary_memory.py tests/test_asap3_hidden_limits.py` → пусто. База правок: `b90049af^`.

## Вердикт: **Needs Fixes**

Блокер один: **#12 закрыт не полностью** — мемы досье по-прежнему теряются в SQL `LIMIT 10` до нового подсчёта, поэтому production-WARN `memes_kept=10/15` недостижим; тест это маскирует заглушкой, игнорирующей `limit` (тот же класс ошибки, что F2 первого ревью). Остальные 4 пункта (#11, #13, #14, #19) подтверждены. Бюджеты не ослаблены.

## Acceptance ledger

| Пункт | Статус | Доказательство |
|---|---|---|
| 1. Досье: totals до срезки (10/35, 10/15), WARN в обеих ветках, заголовок честный | **FAILED (частично)** | Факты: `get_persona_card` не лимитирует факты (`database.py:11018-11024`), 30+5 → `facts_kept=10/35`, заголовок «35 фактов» — VERIFIED (тест). Мемы: сервис зовёт `list_chat_memes(..., limit=_PERSONA_MAX_ITEMS=10)` (`direct_chat_service.py:8083`), а БД применяет `LIMIT ?` (`database.py:11222-11244`) → до сервиса доходит максимум 10, `memes_total` никогда >10; WARN `10/15` невозможен, потеря 11..N молчит. Тест `tests/test_asap3_hidden_limits.py:193-194` игнорирует `limit` и отдаёт 15 — недостижимый seam. |
| 2. Примеры: eligible/selected/dropped, total=20 kept=4, WARN, совместимость | **VERIFIED** | Реальный seam резолвера (`mca_sample_library.py:1434-1441`), тест `test_expression_resolver_counts_approved_rows_before_item_cap` (20→4, stats 20/4/16, WARN `kept=4/20 by=items`); `ExampleRender` — str-совместимый; 52 теста слоя зелёные. |
| 3. `room==0`: WARN, маркер выживает, текста в логе нет | **VERIFIED** | `direct_chat_service.py:6674-6682`; тест `test_current_question_dropped_when_markers_fill_cap` (маркер в блоке, `я`-текста нет). |
| 4. Хвост 8000: WARN на трёх срезах, бюджет не изменён, классификация исправлена | **VERIFIED** | `summary_memory.py:1252-1261`, `:3315-3322`, `:5307-5314`; `_FACT_EXTRACT_MAX_CHARS=_GRAPH_EXTRACT_MAX_CHARS=8000` не менялись. Тест memorize + живая проба YouTube 8500→WARN. Граф-срез проверен чтением кода (тот же паттерн). #19 в инвентаре = HIDDEN_LOSS. |
| 5. #14: тест WARN + честная классификация (защита API 422) | **VERIFIED** | `_clip_field` (`mca_sample_library.py:565-586`), тест `test_sample_field_clip_is_logged`; `SampleWrite` max_length 2000/4000 (`web/api/speech.py`) → UI 422; TECHNICAL_VISIBLE/defense-in-depth — честно. |
| 6. Нет ослабления бюджетов; изменения аддитивны | **VERIFIED** | 4/140/700, 10/1200, 800, 2000/4000, 8000 не изменены; diff — счётчики/логи; первые 4 строки резолвера и байты блока примеров для ≤4 строк те же; заголовок 10→35 — требуемая правка F1, не ослабление. |
| 7. Прогон | **VERIFIED** | `test_asap3_hidden_limits.py` — **13 passed**; 13 затронутых файлов — **371 passed**; memory-набор — **203 passed**; 0 failed. |

## Findings

### F1 (BLOCKER) — #12: мемы досье всё ещё теряются в SQL LIMIT, `memes_kept=10/15` недостижим
- Требование: п.1 приёмки (totals до срезки, 10/15) и §2 «технический лимит не скрывает потерю».
- Где: `direct_chat_service.py:8083` → `database.py:11222-11244` (`LIMIT ?`); тест `tests/test_asap3_hidden_limits.py:193`.
- Репро (production-подобный seam, fake соблюдает `limit`): 3 факта + 5 защищённых + 15 мемов → карточка показывает 10 мемов, WARN **нет**, 5 мемов исчезают молча; `memes_total=10`. В тесте 15 мемов возможны только потому, что заглушка игнорирует `limit`.
- Влияние: владелец с >10 мемами не видит потери; evidence §3.2 (`10/15`) и строка #12 «исправлено» не подтверждены; green-тест защищает невозможный seam.
- Минимум: получить истинный total мемов (COUNT или чтение без display-лимита 10 + срезка в сервисе) и считать `memes_total` от него; заглушку теста сделать соблюдающей `limit` (или тест на temp SQLite через `list_chat_memes`), чтобы `10/15` был реальным.
- Recheck: тот же сценарий 3+5+15 → WARN `memes_kept=10/15`; hidden_limits 13.

### F2 (RELATED_SMALL, обязательна для закрытия HID-*) — арифметика классификации в инвентаре
`evidence/limits-inventory.md:50-54`: перечислено **8** TECHNICAL_VISIBLE (№3,4,5,7,9,10,15,14), но написано «7»; HIDDEN_LOSS указан «5» с №14, при этом №14 в таблице — TECHNICAL_VISIBLE; строка «5+7+5+6=23» держится только на двойном счёте №14. Честно: 5 USER_VISIBLE + 8 TECHNICAL_VISIBLE + 4 HIDDEN_LOSS (№11,12,13,19) + 6 NOT_RELEVANT = 23; №14 — defense-in-depth, исправлено 4/4. Без этой правки HID-TECH-VISIBLE/HIDDEN-LIMITS закрывать нельзя (и #12 после F1 всё равно остаётся частично открытым).

### F3 (RELATED_SMALL, узкая) — плоская ветка режет связи без WARN
`irony OFF` — дефолт (`settings.py:3043`). `lines[:_PERSONA_MAX_ITEMS]` (`direct_chat_service.py:8104-8115`) режет общий список, но WARN срабатывает только при `n>10`. Проба: 5 фактов + 8 связей → в карточке 5 связей, в заголовке «8 связей», WARN нет. §6 п.4 («заголовок показывает число вошедших связей») для плоской ветки неточен. Минимум: WARN с `facts_kept/links_kept` при срезе общего списка или явно записать этот лимит в инвентарь как отложенный. Не блокирует 4 подтверждённых пункта, но не даёт говорить «все потери карточки видимы».

## Числа и проверки
- `13 passed` (hidden_limits) · `371 passed` (13 затронутых файлов) · `203 passed` (memory) · 0 failed.
- Пробы: YouTube 8500 → `clipped 8500 -> 8000`; production-подобный досье-seam 15 мемов → 10 в карточке, WARN нет; плоская карточка 5 фактов + 8 связей → 5 связей, WARN нет.
- Код/диффы прочитаны: `direct_chat_service.py`, `dossier_prompts.py`, `mca_expression.py`, `mca_sample_library.py`, `summary_memory.py`, тест-файл, инвентарь, `database.py:11003-11039,11222-11244`, `web/api/speech.py:SampleWrite`.

## Можно ли закрывать HID-*?
**Нет, пока не исправлены F1 (код #12) и F2 (evidence); F3 — закрыть записью/мини-WARN.**
- #11, #13, #14, #19 — подтверждены.
- #12 — факты подтверждены, мемы нет → HIDDEN_LIMITS/HID-AUDIT-MEMORY/HID-FIELDS-6/HID-TECH-VISIBLE не VERIFIED.
- Строки HID-* в `requirements-map.json` пока PENDING с пустым evidence, `candidate_commit` пуст (strict_evidence=true) — PM должен связать evidence после правок и прогнать `--stage review`.