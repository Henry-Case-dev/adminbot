# AdminBot — project.md (аксиомы OpenSpec)

## О проекте

AdminBot — юмористический Telegram-бот «товарищ» для личного чата друзей (реакции, /summary, фактчек, поиск, память) + админ-инструмент: Telegram Mini App (TMA) дашборд для управления параметрами бота. Бот @PERMsoc_bot (id 8802473181), супергруппа -1002661910336. (Источники: MEMORY.md, README.)

## Стек

| Слой | Выбор | Источник |
|---|---|---|
| Рантайм | Python 3.12+, asyncio | MEMORY.md, README |
| Telegram | aiogram 3.x (`>=3.31,<4`, rich_message/локальный режим) | MEMORY.md, requirements.txt |
| LLM | deepseek-v4-flash через apinet.cloud (OpenAI-совместимый, провайдер-агностик), фолбэк DeepSeek direct; эмбеддинги gemini-embedding-001 (dim 3072); Groq whisper-large-v3 → OpenRouter fallback | MEMORY.md |
| Хранилища | SQLite + sqlite-vec + FTS5 (память бота); PostgreSQL 16 + asyncpg (админка; Docker, слушает только 127.0.0.1) | MEMORY.md |
| Тесты | pytest + pytest-asyncio; прод-база постоянно растёт (3111+ по README; 3280 passed на 31.08). **Правило: полный прогон перед каждым коммитом, 0 регрессий** | README, MEMORY.md |
| Прод | сервер 198.46.175.136, systemd `admin_bot`, `git pull --ff-only`, `TimeoutStopSec=30`; домен admin-bot.duckdns.org (DuckDNS + Caddy + Let's Encrypt) | MEMORY.md |

## Git и процессы

- `plans/` коммитится в git (кроме секретных файлов); conventional commits на русском; `git diff --check` чист.
- Медиа-файлы (`media/`) добавляются/удаляются СОЗНАТЕЛЬНО для сервера; НЕ в .gitignore, НЕ удалять без указания.
- Эталон + код + тесты — одним атомарным коммитом (прецедент D123).

## Процесс: memory-sync авто-коммит (T-725)

- memory-sync — это `plans/docs/memory-project-overview.md`, отчёты `plans/docs/*-research.md` и обновления KG-индекса в них.
- В конце каждого раунда @DevOps коммитит memory-sync **автоматически** отдельным docs-коммитом на русском, БЕЗ запроса разрешения (в составе финального docs(plans)-коммита раунда).
- Перед docs-коммитом обязательна проверка на секреты: grep-паттерн реальных токенов/ключей (`api[_-]?key|token|secret|password` и значения-секреты из контекста раунда) по `git diff` + визуальный осмотр диффа; найденное — вычистить.
- `.env` и реальные токены не коммитятся никогда (R17); в git попадает только `.env.example` с плейсхолдерами.
- Прецедент первого применения: раунд 4 (04.09.2026), финальный docs(plans)-коммит @DevOps.

## Секреты (R17)

- Только `.env` на сервере; в коде/`.env.example` реальных значений нет.
- В UI/логах маскировка `{configured,last4}`; `sanitize()` в log_ring; ключи не логировать.

## Каноны «НЕ трогать» (байт-в-байт дисциплина)

Эталоны промптов живут ТОЛЬКО в `plans/docs/canon/`:

- `docs/canon/backlog.md`: R11 (summary SYSTEM_PROMPT, 22 строки), R42-6 (CHECKUP_SYSTEM_PROMPT), R46-2 (промпт-экстрактор), R46-4 (XML-шаблон + инструкция «Если в блоке <bot_knowledge>…» во все системные промпты).
- `docs/canon/architecture.md`: EXTRACT/CHECKUP/SEARCH/YOUTUBE/WEBPAGE/FACTCHECK (Sections 35.3/51.4/55.7/72.1).
- Прочие каноны: R50-4 CHAT_SYSTEM_PROMPT, пулы R50-7/8 и R42-2/3/4/5, R11 SUMMARY UX-фразы (R13), D224 цепочка /info (`DEFAULT_INFO_TEXT` = `info_text.md` = ARCH 53.3 = R44-1), `info_text.md` как сид-источник (84.13), media/-политика, R17.

Правка эталона = правка константы в коде + эталон + тесты одним коммитом.

## Инварианты архитектуры

- Порядок роутеров aiogram (bot.py) критичен и не меняется; узкие хендлеры до широких.
- `return UNHANDLED`-пропагация (D49); не `SkipHandler`; не Force Reply; Group Privacy не выключать без узкого фильтра (Н1 BotFather).
- Списки/настройки — в конфиг (админку), не хардкодить; чтение через `hot.get(key, settings_default)`.
- Не Mem0/Zep/Letta; бот строго реактивный (планировщик — только саммари/рассылки).
- Дефолты-решения D238: молчание после 5 кулдаунов; стриминг только саммари; typing без паузы; «🗿»; системные промпты не менять.

## Статусы OpenSpec

- `features/<kebab>/spec.md + tasks.md` — активные фичи; статусы задач `[x]`/`[ ]`, `⏸` = «ждёт человека», не закрывать.
- `backlog.md` = только неначатые глобальные эпики.
- Завершено → `archive/`. Закрытые эпики и легаси-планы удалены 03.09.2026 по решению владельца; тексты сохранены в git-истории (plans/ до реструктуризации).
