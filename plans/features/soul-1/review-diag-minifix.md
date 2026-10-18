# REV-DIAG-MINIFIX — вердикт (мини-фикс диагностики инициативы, P0A-INIT)

Независимое ревью. Read-only; этот коммит — только данный документ.
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
**Needs Fixes** — единственный блокер F1 (goal-фолбэк ломает заявленную byte-идентичность извлечения в достижимом краевом случае). Правка микроскопическая (§1); после неё и мини-речека вердикт переводится в Approved без повторного полного прохода.
