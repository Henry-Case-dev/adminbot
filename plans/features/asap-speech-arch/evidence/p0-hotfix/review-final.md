# P0 CORRECTIVE — финальный независимый review (live final4)

- **Кандидат кода:** `59922de52461129ac2e10a66c472d699587cf860` (ветка `task/speech-p0-hotfix`), docs HEAD `f50b28dd`; код-предок `c0d5a3d3`; база `534ac7dd` (prod 2.58.130).
- **Live-доказательство:** `probes_final4/` на `59922de5`; staging `/tmp/p0-final4/new`, 421 файл; прод не менялся. `manifest.verdict = FAILED`.
- **Вердикт: Needs Fixes.** Деплой запрещён. L1 A, мета-вступления и точность цитат не приняты; карта требований не готова.

## 1. Блокеры

### F1 — L1: исходный запрос A снова `answer/compact` (Builder)
- Требование: `source-owner-p0-corrective-2026-10-25.md:33-37` — явный запрос «проанализируй мои сообщения в чате» должен получать research/deep; оба исходных запроса, natural и forced.
- Факт на `59922de5`: `raw_new_A`: `response_act=answer`, `extent=compact`, `structure=answer`, `mode=casual`, `analysis_predicate=false`, 204/317 симв., в payload **0** `как разбирать:`/`ANALYSIS_*`. `raw_new_B` — research/normal, analysis 1×1; forced A/B — 2/2 research. На `c0d5a3d3` (`probes_final3`) A/B были research 2/2 — новый канон ред.3 коррелирует с регрессией.
- Влияние: владелец получает поверхностный ответ вместо разбора истории; это ровно исходный дефект §1.1.
- Минимальная коррекция: поправить семантику правила 3/7 активного L1 (без списков фраз), чтобы прямой запрос анализа истории не превращался в `answer/compact`; silent-правило сохранить.
- Recheck: тот же harness final4, A/B natural по 2 повтора + forced A/B; требование A/B research 2/2, payload A с analysis-блоком.

### F2 — Writer: мета-вступления остались (Builder)
- Требование: `source-owner-p0-corrective-2026-10-25.md:156` — убрать лишние мета-вступления; `NO_META_STRUCTURE_TEXT` в payload ровно 1×.
- Факт: 3/16 первых предложений new/forced: A1 «**Ну**, ты не злобный…», E1 «**Давай** без лишних церемоний.», E2 «**Окей, глянул** твою простыню.». Даже если считать «Ну» только filler (директива прямо запрещает «ну»), остаются 2 явных анонса процесса.
- Влияние: ответ начинается со служебной подводки, а не с сути; требование владельца не выполнено.
- Минимальная коррекция: усилить writer-правило либо добавить узкий guard первого абзаца, убирающий только анонс процесса (не длину и не содержание).
- Recheck: 16 new/forced ответов, 0 первых предложений-анонсов; отдельно E1/E2.

### F3 — Цитаты: 26/45 не exact, часть — изменённые слова (Builder)
- Требование: `source-owner-p0-corrective-2026-10-25.md:179` — нет неподтверждённых дат и цитат; `QUOTE_FIDELITY_TEXT` 1× в research/deep payload.
- Факт: 45 кавычек, 19 exact, 6 склеек/многоточий, **20 с изменёнными словами/пересказом**. Примеры: `«…чуствуется на коже»` (в payload `чувствуется`), `«…не нравитса…»` (в payload `не нравится`), `«супермега хейтом»` (в payload `супермега хейт`), `«жертва-эстет»` и `«главного хулителя и музыкального диктатора»` в payload отсутствуют. Это не выдуманные даты/события, а пересказ/опечатки в кавычках; но правило «цитата только дословно, иначе без кавычек» нарушено.
- Влияние: модель приписывает участникам формулировки, которых они не говорили; подрывается доверие к разбору.
- Минимальная коррекция: либо точная цитата, либо пересказ без кавычек; допустим узкий post-guard снятия кавычек с не-exact фрагментов, без обрезки текста.
- Recheck: E и forced A/B; все кавычки — exact-подстрока payload или сняты; даты остаются 0.

### F4 — Карта и release-gate не готовы (PM)
- В worktree карта `requirements-map-p0-hotfix.json` — 79 PENDING, без §2 ALIAS/§3 corrective. В master `requirements-map-p0-corrective.json`: 69 items, **67 PENDING, 2 VERIFIED**, `candidate_commit` пуст.
- `L1-ROUTING-REPAIR` помечен VERIFIED на evidence `47fba465`, причём observation сам говорит: «реальный прогон … остаётся за HARNESS/PROBES». Final4 это опровергает. Это ложный VERIFIED.
- `requirements_gate.py check --stage plan` проходит (0 errors), но `--stage review --slice L1 --candidate 59922de5` даёт **9 errors / exit 1**: candidate mismatch, нет candidate-bound evidence, L1-ROOT-CAUSE/L1-NO-FORCED-MODE/L1-HISTORY-DEEP/L1-DEPTH-NOT-LENGTH/L1-NO-HARDCODED/L1-TWO-SCENARIOS — PENDING.
- Минимальная коррекция PM: привязать карту к финальному SHA, перенести final4 raw в evidence, поставить L1-ROUTING-REPAIR FAILED, закрыть только доказанное, прогнать review-gate. Без этого release-gate обходить нельзя.

## 2. Что подтверждено

| Проверка | Статус | Доказательство |
|---|---|---|
| Core 3294 / `ead77b2ab509` | VERIFIED | срез `system` offset 3083, 3294, sha12 `ead77b2ab509`; P1–P6; `simplify_core_for_prompt` identity, фильтра нет |
| Нет обрезки ответа | VERIFIED | `extent_scrub_removed=0`; E 2318/2952; A 204/317; `max_tokens=2400` — лимит генерации, не постобрезка |
| RAG/Memory | VERIFIED | rows 40, after_dedup 39, kept 39, block 2027, 18 «не подтверждено», 4 «предположение», 22 `[чат]`, 0 `[Бот]` |
| FREQUENT | VERIFIED | `frequent_text=true`; occasional/off=false; PG global/chat `profanity=frequent` rev2; мат фактический, few-shot не обязателен |
| E не silent | VERIFIED | `reply/research/detailed`, 2318/2952, содержательный |
| F историческая честность | VERIFIED | «не было конфликта… если что-то серьёзное и было — я это пропустил»; 0 self-echo |
| Даты | VERIFIED | 0 годов/дат в new/forced |
| Структура | VERIFIED | нумерация только E2 при явной просьбе E «подробно… с примерами»; B/C/D/F/forced без списков |
| Alias в payload | VERIFIED | 8/8 new/forced: `Гипербореец=0`, `author=Макс`, `alias_probe.source=chat`, uid `42115912` → `Макс` |
| Alias-тесты | VERIFIED | 73 passed alias + 290 passed P0-subset; `review-alias.md` 11/11; F5 protected writer — остаточное, без writer'а эффекта нет |
| Alias hot-reload | **UNVERIFIED** | код `_refresh_turn_aliases` в начале хода + a5/a19; но смены алиаса в живом процессе не наблюдали. Нужен один in-process turn до/после `set_chat_params` с capture (без прода). |
| Old lore | VERIFIED | `272170e3` — предок; точечный quarantine id=3/4; общий предикат baseline/фасад; `lore_graph_slice` без BOT_ORIGINS/tentative; PG marker в `format_lore_block`; массового DELETE нет; 347 тестов |
| Fallback/retry | VERIFIED (scope) | diff не удаляет fallback/retry; final4 `invalid=0`, `fatal` нет; targeted 427 passed. Полный suite 1739 не перезапускался — это остаётся evidence-gap, не продуктовый дефект. |
| Deploy safety | VERIFIED (preconditions) | prod 2.58.130 @ `534ac7dd`; 13 untracked — бэкапы/мусор, не патчи; `git diff` пуст; reset/clean не нужен; PG migration `6c2ddc17c998` → `cc020660ae03` в `PROMPT_MIGRATIONS`, откат P0CS3→P0CS2→P0CS→R3b→R3→2.58.113 |
| Нет postprocess/скрытых обрезок | VERIFIED | meta/quote — только prompt; ответы не режутся; Core полный. Именно поэтому F2/F3 — дефект соблюдения инструкции, а не обрезки. |

## 3. Не блокирует, но зафиксировано
- `manifest.versions.core=0` при слое 3294 — дефект отчётности harness, не продукта.
- `list_lessons` traceback (`store=None`) в new/old — известный дефект стенда.
- Два SSH-логина в final4: первый упал до upload/LLM, прод не менялся; процессное нарушение, не продуктовый дефект.
- `protected_facts.subject_ref_id` — разная семантика с `graph_facts`; writer'а per-user protected-фактов нет, эффекта сейчас нет.
- Полный suite не перезапускался; targeted 137 + 73 + 290 = 500 passed (пересечения между наборами возможны), полный 1739 — за CI/DevOps.

## 4. Checks performed vs reused
- Самостоятельно: source/§1–§5, `probes_final4.md` + 10 raw, raw-анализ мета/цитат/длин/Core/alias/RAG, `probes_final3` A/B, `active-core.md`, `old-lore-audit.md`, `prod-worktree-alias.md`, diff `534ac7dd..HEAD`, L1/writer/core/lore code, `requirements_gate` plan/review, pytest 137 + 73 + 290.
- Переиспользовано: `review-alias.md` (11/11), alias 73/290, old-lore 347, prod-worktree 13 untracked; проверено на текущем кандидате, код alias/lore с `f42e2257` не менялся.
- Внешние источники/браузер: не требовались — вопрос repo-local, UI не менялся.

## 5. Следующее действие
1. Builder: F1, F2, F3 — минимальные правки, без новых квот и без обрезки; затем тот же final4 harness, A/B 2/2 + forced 2/2, meta 0/16, quote exact.
2. Builder/alias: один in-process turn с изменением алиаса (hot-reload), capture payload.
3. PM: привязать corrective map к новому SHA, L1-ROUTING-REPAIR = FAILED до recheck, final4 raw в evidence, review-gate EXIT 0.
4. Reviewer: повторный независимый recheck точного нового кандидата. Деплой — только после этого; прод остаётся 2.58.130 @ `534ac7dd`.