# AdminBot — backlog.md (глобальные неначатые эпики)

Только эпики, которые можно начать планировать. Канон-блоки промптов — в `docs/canon/`; закрытые эпики 1–85 — история в git-истории (прежние файлы plans/, удалены 03.09.2026).

## Epic 86: GraphRAG → PostgreSQL

Миграция GraphRAG-хранилища (граф nodes/edges, векторы, индексы, TTL/cleanup) с SQLite на PostgreSQL 16 (asyncpg). Извлечена из Epic 85 (решение человека 30.08). **Статус:** future/planned; Epic 85 закрыт 30.08 → можно начинать планировать (нужен DESIGN @Architect + аппрув человека). (Источники: board.md, backlog.md:8435-8437 в git-истории до 03.09.2026, MEMORY.md.)

## Epic: Улучшения фактчека (аудит FACTCHECK_AUDIT)

4 рекомендации «вне скоупа» из аудита 2026-08-20: (1) жёсткий вердикт-формат в промпте + обязательные источники; (2) параллельный каскад Tavily+Exa (замена последовательного); (3) кэш проверок claim→hash→TTL 1ч; (4) query expansion. **Статус:** не начат; НЕ связан с отложенными идеями RESEARCH_HUMAN. (Источник: FACTCHECK_AUDIT.md в git-истории до 03.09.2026; выжимка — `docs/factcheck-audit.md`.)

## Bugfix-раунд 04.09.2026: TG-видео-команды, безопасный direct-stream, Tool Calling-фиксы

Bugfix-раунд после эпика 04.09 (архив ниже). Три блока: (1) «транскрипт/че за видос/о чем видео/поясни за видос/перескажи видос/че в видосе» работают ТОЛЬКО для YouTube-URL (handlers/youtube.py:47-107: парсер возвращает `(None, None)` без URL → UNHANDLED), обычные TG-видео (video, документы mime video/*, в т.ч. репосты/forward) никем не обрабатываются — единственный медиа-хендлер `F.voice|F.video_note`; (2) маршрутизация скачивания: `is_direct_media_url` стримит «прямые» `.mp4/.webm/...` даже у известных платформ (youtube/tiktok/instagram/vk/x/rutube и пр.), у direct-ветки «скачай» нет `cooldown_touch`, реплай «скачай» на видео-сообщение не разбирает `reply_target`; (3) tool calling direct_chat: `CHAT_SYSTEM_PROMPT` не упоминает инструменты, description'ы `query_chat_memory` не покрывают счётные вопросы («сколько раз…»), результат тула не содержит count/даты, возможна тихая деградация на 1-м раунде (`tool_loop.py:37-49`). **Статус: ✅ Выполнен и заархивирован (04.09.2026), см. plans/archive/tg-video-tool-calling-fixes/** — 3526 passed, 0 failed, аппрув @Reviewer; архитектура — `ARCHITECTURE.md` §14. Вне архива: README-правки, коммит всего, пуш, деплой и live-верификация (T-683…T-685) — финальный шаг @DevOps. (Источник: контекст-диагностика @PM 04.09, MEMORY.md.)

## Epic: Мультимодальная саммаризация, Tool Calling, рефакторинг реакций и UX/UI админки (АРХИВ)

4 части: (1) каскадная видео-выжимка через OpenRouter `video_url` — primary `minimax/minimax-m3:free`, fallback `google/gemma-4-31b-it:free`, затем старая логика субтитров (graceful degradation); (2) Tool Calling — `execute_web_search`, `query_chat_memory`; (3) фиксы реакций — тумблеры `reactions.vasya_enabled`/`reactions.kucha_enabled`/`flags.mimic_enabled`/`reactions.alan_mimic_enabled` (default `false`), строгий гейт `slavic_chlen.mp4` по `reactions.slavik_user_id`, Alan → Леха; (4) UX/UI админки — группировка вкладок, KV-редактор `limits.summary_aliases`. **Статус: ✅ Выполнен и заархивирован (04.09.2026), см. plans/archive/multimodal-summarization-tools-reactions-ui/** — 3447 passed, 0 failed, аппрув @Reviewer; архитектура — `ARCHITECTURE.md` §13. Вне архива: деплой и живая верификация (T33/T34) — шаг @DevOps; финальный memory-sync — шаг @Memory.

---

Сознательно отклонённые/отложенные идеи (RESEARCH_HUMAN): per-bot throttle, wallet на чат, triage-гейт, TTS, мемы и пр. — НЕ активны, см. `docs/research-directchat-digest.md`. Закрытые эпики 1–85 — история в git-истории (прежние файлы plans/, удалены 03.09.2026).
