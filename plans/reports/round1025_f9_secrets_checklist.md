# F9 round1025 — чек-лист секретов §50 (T-3034): «параметр → экран → поведение маски»

> Источник каталога: `services/param_catalog.py` (`_KEYS`/`_INFRA`, 28 записей с `secret=True`).
> `Δ каталога = 0` — новые ParamSpec/группы НЕ добавлялись; 28 секретов распределены по существующим экранам.
> Поведение (F9/ADR-1025-22 D1/D3): поле ввода **всегда пустое**, маска/«Ключ установлен» — display-индикатор
> (`secret-field`), не значение `input` (§50/R17). «Заменить» = ввод + SaveBar; «Удалить» = confirm (D2).

## A. UI-редактируемые секреты — 20 (`category=keys`)

| № | Параметр (`keys.*`) | Группа | Экран (вкладка) | Поведение маски |
|---|---|---|---|---|
| 1 | `keys.llm_api_key` | keys_llm | Настройки AI → LLM Провайдеры | `••••••••last4` / «Ключ установлен»; поле пустое |
| 2 | `keys.llm_fallback_api_key` | keys_llm | LLM Провайдеры | то же |
| 3 | `keys.embedding_fallback_api_key` | keys_llm | LLM Провайдеры | то же |
| 4 | `keys.embedding_fallback_api_key_2` | keys_llm | LLM Провайдеры | то же |
| 5 | `keys.embedding_api_key` | keys_llm | LLM Провайдеры | то же |
| 6 | `keys.intel_history_api_key` | keys_llm | LLM Провайдеры | то же |
| 7 | `keys.intel_bg_api_key` | keys_llm | LLM Провайдеры | то же |
| 8 | `keys.intel_reflection_api_key` | keys_llm | LLM Провайдеры | то же |
| 9 | `keys.tavily_api_key` | keys_search | LLM Провайдеры (per-field «Проверить») | то же; проба шлёт `api_key:''` |
| 10 | `keys.exa_api_key` | keys_search | LLM Провайдеры (per-field «Проверить») | то же |
| 11 | `keys.groq_api_key` | keys_groq | LLM Провайдеры | то же |
| 12 | `keys.openrouter_api_key` | keys_openrouter | LLM Провайдеры | то же |
| 13 | `keys.media_share_secret` | keys_media | LLM Провайдеры | то же |
| 14 | `keys.image_api_key` | keys_images | LLM Провайдеры + карточка «Генерация изображений» | то же; **globalSecret** → «Удалить» = `DELETE /api/config/keys/own/{key}` (BYOK ON), иначе F0 empty-write |
| 15 | `keys.youtube_transcript_proxy_url` | keys_youtube | Модуль «Выжимка видео» | то же |
| 16 | `keys.youtube_transcript_proxy_username` | keys_youtube | «Выжимка видео» | то же |
| 17 | `keys.youtube_transcript_proxy_password` | keys_youtube | «Выжимка видео» | то же |
| 18 | `keys.youtube_cookies_file` | keys_youtube | «Выжимка видео» | то же (путь, не токен — но помечен secret) |
| 19 | `keys.checkup_betterstack_sql_user` | keys_betterstack | Модуль «Чек-ап» | то же |
| 20 | `keys.checkup_betterstack_sql_password` | keys_betterstack | Модуль «Чек-ап» | то же |

**BYOK-ключ чата** (`keys.llm_api_key`, scope=`chat`): карточка «Ключ чата (BYOK)» — тот же компонент `secret-field`
(`scope='chat'`), статус `{configured,last4}` из `GET /api/config/keys/status`; «Использовать мой» = PUT own,
«Удалить» = `DELETE /api/config/keys/own/{key}`.

## B. env-only инфраструктурные секреты — 8 (осознанно вне UI)

| № | Параметр | Категория | Экран | Поведение |
|---|---|---|---|---|
| 21 | `API_TOKEN` | None (infra) | — | env-only (вне UI), безопасность |
| 22 | `POSTGRES_DSN` | None (infra) | — | env-only (вне UI) |
| 23 | `POSTGRES_PASSWORD` | None (infra) | — | env-only (вне UI) |
| 24 | `SENTRY_DSN` | None (infra) | — | env-only (вне UI) |
| 25 | `LOGTAIL_SOURCE_TOKEN` | None (infra) | — | env-only (вне UI) |
| 26 | `TELEGRAM_API_ID` | None (infra) | — | env-only (вне UI) |
| 27 | `TELEGRAM_API_HASH` | None (infra) | — | env-only (вне UI) |
| 28 | `COBALT_HTTP_PROXY` | None (infra) | — | env-only (вне UI) |

## Итог
- **28/28** секретов классифицированы: **20 UI** (`category=keys`, редактируются через единый `secret-field`) +
  **8 env-only** (вне UI, осознанно — инфраструктура/безопасность).
- **«Без экрана» = 0** в смысле отсутствующих UI-полей: у всех 20 UI-секретов есть экран и корректный
  display-индикатор маски; 8 env-only — намеренно не в UI (не «забыты»).
- Ни один секрет не раскрывает сырое значение в браузер/POST/лог (R17): наружу только `{configured,last4}`.
- `Δ каталога = 0`: `services/param_catalog.py` не менялся; перегруппировок/новых Spec нет.
