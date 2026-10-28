# MEMORY-L2-NOT-EVIDENCE — привязка к P0 DELTA / deployed 2.58.134

- Дата: 27.10.2026. Lane PM-VERIFY-L2-NOT-EVIDENCE (read-only + map binding).
- Референс кода: `release/p0-2026-10-26` @ `d454ad93` (предок текущего tip
  `297bc5d8`, APP_VERSION = 2.58.134, `config/settings.py:3375`) — проверено
  `git grep`/`git show` по коммиту, код не менялся, тесты не запускались.
- Acceptance строки L00161 карты `requirements-map-p0-corrective.json`:
  «Пересказ L2 не выступает самостоятельным доказательством: он помечен как
  пересказ, факты опираются на первичные записи».

## Clause (a) — пересказ помечен (payload speech-side, Direct Chat)

- `services/direct_chat_service.py:5795` — L2 (широкий фон) в payload:
  `"широкий фон: пересказ, не источник: " + level2_text` (head_lines,
  direct-композер; докстринг :5763).
- `services/direct_chat_service.py:5810` — бегущий конспект:
  `"фон: конспект из N сообщений, ниже дословно свежий хвост — пересказ, не
  источник"` — конспект отличён от дословного хвоста.
- `services/direct_chat_service.py:8835` / `:8838` — тот же маркировкой в
  legacy/глобальном билдере `_build_global_context` (докстринг :8780 —
  SPEECH-P0-A2: «шапка конспекта — не цитата»).
- `services/lore_prompts.py:128` — `(летопись чата: пересказ, не источник
  фактов)` для lore-канала.

## Clause (a) — origin-метки производных фактов (tool path, дефект 5 аудита)

Аудит (`plans/features/p0-delta-analysis/evidence/audit.md` §8, §9.5) нашёл
дефект 5: read-side провенанс не доезжал до модели в memory-тулах (bd6d5fff).
P0 DELTA закрывает:

- `services/tool_router.py:210-221` — `_DIG_FACT_ORIGIN_LABELS`:
  `chat_history→[пересказ из чата]`, `derived_belief→[вывод бота]`,
  `user_memory→[запомнено]`, `bot_self_reply/bot_direct_reply→[прошлые слова
  бота]`, `[из статьи]/[из видео]/[из голосового]` и т.д.; неизвестный
  origin — сам origin (`_fact_origin_label`, :1071-1079).
- `services/tool_router.py:1424-1435` — каждая строка dig facts =
  `{origin-метка} {строка факта}`; `status=archived_belief` → суффикс
  «(архивное убеждение)».
- `services/tool_router.py:912-915` — vector/RAG fallback в
  query_chat_memory — отдельный блок с заголовком «Контекст из памяти
  (обобщённые факты и пересказ, не дословные сообщения):».
- `services/summary_memory.py:1390-1412` — `build_rag_context(...,
  origin_labels=True)` рендерит «[{label}] {текст}» — direct-RAG
  `<RAG_Memory>` видит источник каждой строки (`direct_chat_service.py:8671`).
- Тесты: `tests/test_p0_delta_routing.py:723-786` (chat_history→
  [пересказ из чата], derived_belief→[вывод бота], unknown→[weird_source],
  archived_belief→суффикс, msg-сниппеты без меток) — D5 CLOSED в
  `review-delta.md` (ревизия 2ac20bf3, Approved, D1-D5 все CLOSED).

## Clause (b) — факты опираются на первичные записи

- `services/direct_chat_service.py:1899-1907` + `:8587` (SPEECH-P0-A2):
  выводы бота (`bot_self_reply`/`bot_direct_reply`,
  `provenance.is_self_referential_origin`) в ФАКТИЧЕСКИЙ RAG не попадают —
  прошлые ответы остаются только в `<style_anchors>` как интонация;
  ранжирование существующим `graphrag_provenance.read_policy_rank`:
  rank 2 → пометка «(предположение)», rank 0/1 → «(не подтверждено)»
  (`_RAG_UNCONFIRMED_MARK`/`_RAG_TENTATIVE_MARK`, :1909-1910).
- `services/direct_chat_service.py:8682` + `services/summary_memory.py:614-617`
  — self-echo инструкция в `<RAG_Memory>` при наличии self-строк: «Ниже —
  твои ПРОШЛЫЕ слова. Относись к ним критически: ты мог шутить, отыгрывать
  роль или ошибаться.»
- kind="msg" сниппеты — дословные первичные записи корпуса, без меток
  пересказа (`tool_router.py:206-208`, комментарий к `_DIG_FACT_ORIGIN_LABELS`).
- Runtime-подтверждение на кандидате bd6d5fff: RUN-6 [M-L2] (маркер
  «пересказ, не источник» в L2 keep-head) и [M-SELF] (bot_self_reply/
  bot_direct_reply не попадают в фактический RAG) — `evidence/p0-hotfix/
  alias-tests.txt`, 9 passed.

## Вывод

Обе части acceptance выполнены на задеплоенной линии 2.58.134 (d454ad93):
пересказы/выводы помечены в payload (speech-side head_lines + RAG origin
labels + tool-side origin-метки, дефект 5 закрыт), фактический RAG опирается
на первичные записи (self-echo исключён, производные помечены «(не
подтверждено)»/«(предположение)», дословные msg-сниппеты отличимы).
Незакрытого гэпа нет; строке статус VERIFIED корректен.
