# REV-DIAG-MINIFIX — вердикт (мини-фикс диагностики инициативы, P0A-INIT)

Независимое ревью. Read-only; этот коммит — только данный документ.
**СТАТУС: Approved** — F1 закрыт правкой варианта B (recheck, см. Addendum; исходный Needs Fixes сохранён ниже как история).
**Кандидат:** три uncommitted файла (общая поверхность `d45194d4`). Идентичность: blob12 == `39589fc532bc` / `4093e48d97cf` / `263918982bec`; sha256_12 == `c42a8ecbe48f` / `e774d5fda58f` / `9cc922472cd4` — совпало и в рабочем дереве, и в изолированном worktree (патч применён к `d45194d4`).
HEAD на момент ревью: `7356db49` (чужой docs-коммит review-persist-fix; между ним и базой — ещё чужой `72fa3323`); `git diff d45194d4 7356db49` по нашим трём файлам пуст — кандидат не затронут переездом базы, воркер HEAD не двигал.

## 1. Извлечение `build_opportunity_row` — НЕ byte-identical: найден F1
Сверка с `f0bd29e2`/HEAD-версией: `chat_id=int()`, `kind=intent_kind`, `origin='observer_opportunity'`, `status='ephemeral'`, `created_at=now` (now=int, `int(now)` не меняет), `source_refs=rows[:4]` — совпадают. **Расхождение — goal-фолбэк:**
- было (HEAD, строка 1343): `_mi.canon_text(goal or kind) or kind`, где `kind` = **оригинальный** verdict-kind (`dispute/development/humor/...` — `OPPORTUNITY_KINDS` ∪ `development`);
- стало: helper получает `kind=intent_kind` (маппед), и фолбэк считает `canon_text(goal or intent_kind) or intent_kind`.
- Достижимо: `parse_verdict` → `_canonical_goal(...)= str(canon_text(value) or "")` → пустой goal возможен (LLM-вердикт без goal). Проверено эмпирически в изолированном worktree: при `goal=''` старое поведение даёт `dispute`/`development`, новое — `open_dispute`/`topic_interest`; при непустом goal — идентично (`'тема'`).
- Тесты это не ловят: шов `tests/test_p0_initfix_initiative_observer.py:401–418` пиннит только непустой goal; новый тест — dry-run с непустым goal.
Итог: заявленный принцип «извлечение, строка байт-в-байт» не выполняется в достижимом краевом случае; Writer/L1 в этом кейсе получает другой текст повода.

**Минимальная правка (одна строка), вариант A:** в вызове observer — `goal=goal or kind` (оригинальный kind): helper тогда даёт `canon_text(kind)` == прежнему значению при пустом goal и не меняет поведение при непустом (kind всегда непуст, canon_text его не опустошает). Вариант B (чище): параметр `fallback` в helper (`canon_text(goal or (fallback or kind)) or (fallback or kind)`), observer → `fallback=kind`. Для зеркальности dry-run боевому пути в diagnostics — тот же фолбэк (`goal=str(verdict.get("goal") or verdict.get("kind") or "development")`). Если изменение фолбэка задумано намеренно — это уже смена поведения: нужен явный тест+обоснование и исправление формулировки «byte-identical» в evidence (тогда это решение лейна/PM, не владельца).
Recheck: добавьте мини-ассерт на пустой goal (напр. для `kind='dispute'` ожидать `'dispute'`) и прогоните `test_soul1_w5_initiative_vitality.py` (17) + b01 (13).

## 2. Dry-run wiring — подтверждено
`initiative_diagnostics.run_check`: `intent_kind` (dispute→open_dispute, иначе topic_interest) используется и для кандидата, и для row; row собирается тем же helper (`goal` из вердикта, `rows = await runner._window_rows(...)` — те же окна, что ушли в оценку, `now=started`), передаётся в `dcs.handle_initiative(..., opportunity_row=...)`; mock/publish идут одним вызовом (различается только bot), row от режима не зависит.
Мои прогоны (изолированный worktree @`d45194d4` + патч, 0 чужих изменений): RED — без observer+diagnostics новый тест падает (Writer получил `{}`; совпадает с RED лейна `assert {}`); GREEN — новый тест 1 passed; `test_soul1_w5_initiative_vitality.py` **17 passed**; b01 **13 passed**; группа p0-initfix + w5-gates + mca09-blockE + f6 **65 passed**. Поведение row: `goal='тема'`, `kind='topic_interest'`, `origin='observer_opportunity'`, `status='ephemeral'`, `created_at>0`.

## 3. Дисциплина дерева — подтверждено
Изменены только три файла кандидата; чужие незакоммиченные (config_cache, mca_humor_feedback, prompt_factory, style_policy, summary-тесты и др.) не тронуты; HEAD двигали только чужие docs-коммиты (72fa3323, 7356db49). Мой коммит — только этот вердикт.

## Вердикт
**Needs Fixes** *(исторический статус первой проверки; снят после recheck F1 — см. Addendum)* — единственный блокер F1 (goal-фолбэк ломал заявленную byte-идентичность извлечения в достижимом краевом случае); правка микроскопическая (§1).


## Addendum — REV-DIAG-RECHECK (2026-10-18): F1 закрыт → Approved
Кандидат v2 (uncommitted поверх `a5ab57e0`): blob12 `a057c7311517` / `515f31293971` / `75f0f6cb3c03`; sha256_12 `eef7feec36ac` / `0391fc582f60` / `0272c086f285` — совпало с evidence и в моём изолированном worktree.
- **Код варианта B (прочитан):** helper — `fallback: str | None`, `fallback_text = str(fallback or kind)`, `goal = canon_text(goal or fallback_text) or fallback_text`; наблюдатель зовёт `fallback=kind` (ОРИГИНАЛЬНЫЙ verdict-kind); dry-run — `fallback=str(verdict.get("kind") or "development")` (зеркально); микро-тест `test_check_dry_run_goal_fallback_uses_original_verdict_kind` пиннит `goal=="dispute"` при `kind=="open_dispute"`.
- **Byte-identity воспроизведена моим probe:** новый helper (с маппингом наблюдателя) против inline-выражения `f0bd29e2` на 6 кейсах (dispute/development/humor/memory_recall с пустым goal; event с пробелами; dispute с goal) — полное совпадение строк, `BYTE-IDENTICAL: True` (пустой goal → «dispute»/«development», НЕ «open_dispute»).
- **Прогоны** (изолированный worktree `a5ab57e0` + патч): vitality **18 passed**; F1-микро-тест 1 passed; b01 **13**; группа p0-initfix+w5-gates+mca09-blockE+f6 **65**; combined 78 — с известным пре-существующим флаки: в моих combined-прогонах 2/6 флаков (разные тесты, напр. `test_pending_direct_request_stops_observer_initiative`), на **чистой базе без патча** — 2/3 (тоже разные тесты, тот же `prng journal failed`, DB/aiosqlite-шум); все изолированные прогоны всплывавших тестов — **PASS**. К F1 не относится.
- **Дисциплина:** кандидат = 3 файла + evidence; чужие незакоммиченные не тронуты; этот коммит — только addendum.
- **ИТОГ: Approved** (F1 закрыт; новых находок нет).
