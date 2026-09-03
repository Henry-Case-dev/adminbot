# AdminBot — backlog.md (глобальные неначатые эпики)

Только эпики, которые можно начать планировать. Канон-блоки промптов — в `docs/canon/`; закрытые эпики 1–85 — история в git-истории (прежние файлы plans/, удалены 03.09.2026).

## Epic 86: GraphRAG → PostgreSQL

Миграция GraphRAG-хранилища (граф nodes/edges, векторы, индексы, TTL/cleanup) с SQLite на PostgreSQL 16 (asyncpg). Извлечена из Epic 85 (решение человека 30.08). **Статус:** future/planned; Epic 85 закрыт 30.08 → можно начинать планировать (нужен DESIGN @Architect + аппрув человека). (Источники: board.md, backlog.md:8435-8437 в git-истории до 03.09.2026, MEMORY.md.)

## Epic: Улучшения фактчека (аудит FACTCHECK_AUDIT)

4 рекомендации «вне скоупа» из аудита 2026-08-20: (1) жёсткий вердикт-формат в промпте + обязательные источники; (2) параллельный каскад Tavily+Exa (замена последовательного); (3) кэш проверок claim→hash→TTL 1ч; (4) query expansion. **Статус:** не начат; НЕ связан с отложенными идеями RESEARCH_HUMAN. (Источник: FACTCHECK_AUDIT.md в git-истории до 03.09.2026; выжимка — `docs/factcheck-audit.md`.)

## Epic: Мультимодальная саммаризация, Tool Calling, рефакторинг реакций и UX/UI админки (АРХИВ)

4 части: (1) каскадная видео-выжимка через OpenRouter `video_url` — primary `minimax/minimax-m3:free`, fallback `google/gemma-4-31b-it:free`, затем старая логика субтитров (graceful degradation); (2) Tool Calling — `execute_web_search`, `query_chat_memory`; (3) фиксы реакций — тумблеры `reactions.vasya_enabled`/`reactions.kucha_enabled`/`flags.mimic_enabled`/`reactions.alan_mimic_enabled` (default `false`), строгий гейт `slavic_chlen.mp4` по `reactions.slavik_user_id`, Alan → Леха; (4) UX/UI админки — группировка вкладок, KV-редактор `limits.summary_aliases`. **Статус: ✅ Выполнен и заархивирован (04.09.2026), см. plans/archive/multimodal-summarization-tools-reactions-ui/** — 3447 passed, 0 failed, аппрув @Reviewer; архитектура — `ARCHITECTURE.md` §13. Вне архива: деплой и живая верификация (T33/T34) — шаг @DevOps; финальный memory-sync — шаг @Memory.

---

Сознательно отклонённые/отложенные идеи (RESEARCH_HUMAN): per-bot throttle, wallet на чат, triage-гейт, TTS, мемы и пр. — НЕ активны, см. `docs/research-directchat-digest.md`. Закрытые эпики 1–85 — история в git-истории (прежние файлы plans/, удалены 03.09.2026).
