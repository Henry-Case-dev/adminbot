# Раунд 5: BetterStack-эвристики 401 + лор-инжект чата (миграция v6) + правки канонов промптов с авто-миграцией PG

Спецификация раунда 5 (05.09.2026). База: HEAD `68fb03e` (раунд 4 `betterstack-own-handler-video-memory-cmds`, pytest 3794 passed). Задачи: T-727..T-746 (tasks.md этого раунда). spec.md создан по решению владельца ПОСЛЕ планирования (tasks.md, секция A «spec НЕ создаётся» — устарела). Дизайн финализирован по итогам диагностики; раздел 4.6 содержит дельты, где решения владельца после планирования переопределяют формулировки tasks.md — **для @Builder источником истины является этот spec**.

Проверено по коду HEAD (точечная сверка):
- чтение токена BetterStack: `bot.py:115-116` (`os.getenv` ПОСЛЕ импорта `config.settings`; строго из `.env`);
- стартовая диагностика `bot.py:140-149`, `sentry_dsn = os.getenv("SENTRY_DSN")` на `bot.py:24`;
- хендлер `services/betterstack_handler.py` (rate-gate `_rate_warn` :164-173, `_mark_failed` :215-219, `_post` :175-207);
- миграции: константы схемы `services/database.py:13-17`, цепочка `:217-220` в `initialize()`, прецедент `_migrate_user_memory_v5` `:463-508`, CREATE protected_facts `:383-386` (`user_name TEXT NOT NULL`, `UNIQUE (chat_id, user_name, fact)`);
- `get_protected_facts` `:1343-1351`, `is_fact_protected` `:1673-1679` (по `chat_id`+`fact`, уже ок), `insert_graph_fact` `:1150-1175` (пишет FTS-строку), `delete_graph_fact` `:1659`;
- вызовы protected: `<protected_facts>`-блок `direct_chat_service.py:421/625-638` (escape_xml_text есть), persona `:762-787` (`get_protected_facts` :771), рендер `- {escape_xml_text(fact)}` :636;
- промпты: `chat_prompts.py` (LEGACY :13-23, канон раунда 4 :25-42, п.1 :30, п.2 :31, `migrate_direct_chat_prompt_if_legacy` :47-66), `summary_prompts.py` (SYSTEM :10-33 п.1 :15; COMPRESS :35; EXTRACT :38-48), `checkup/factcheck/search/youtube(×2)/web_prompts.py` (п.1 «чередуй заглавные и строчные…», п.3 TYPO уже единый), PG-ключи 9 штук в `services/param_catalog.py:232-260`;
- bot.py: вызов легаси-миграции `:595-599` (импорт `:598`), `migrate_direct_reply_ttl_default` `:601-604`, `on_startup` `:185-189` (`db = DatabaseService(settings.DB_PATH)`; `db.initialize()` — здесь цепочка миграций v1..v5, затем v6), `main()` вызывает `on_startup()` на `:606`;
- тест-эталоны канонов читают `plans/docs/canon/backlog.md` (якорь «### Системный промпт (R11», таблица R42-6) и `plans/docs/canon/architecture.md` (блоки `NAME = """..."""`).

## 1. Обзор (Overview)

### Контекст и цели раунда (фаза 1, 4 пункта)

1. **BetterStack 401** — root cause найден и НЕ в коде: в прод-`.env` переменная `LOGTAIL_SOURCE_TOKEN` содержит **public key из SENTRY_DSN** (байт-в-байт совпадает с `https://{pubkey}@` внутри DSN), а не Source Token из BetterStack → Logs → Sources. Код читает токен корректно (`.env` → `os.getenv`, bot.py:115-116); env-окружение чистое (`/proc/<pid>/environ` пуст). **Делаем только диагностику/эвристики — чтение токена и конструктор хендлера НЕ меняем** («код по токенам больше не меняем»).
2. **Лор-инжект (чат 2661910336)** — конфа (джаббер-конференция «с нулевых», Пермь, переезды ВК→ТГ) ошибочно идентифицируется ботом как екатеринбургская. Механика: чат-уровневые protected-факты (`user_name IS NULL`, миграция v6) видны ВСЕМ юзерам чата в `<protected_facts>` ВСЕГДА + лор в graph_facts (`origin='user_memory'`, вечно, FTS) + идемпотентный `ensure_chat_lore` при старте бота и по DevOps-скрипту.
3. **sqlite→PG (Epic 86)** — НЕ выполняется (заморожено решением владельца 04.09.2026; T-742 [x] — пометка в `plans/backlog.md` уже внесена). Код не трогаем.
4. **Промпты** — унификация стиля «торопливое письмо» + единый запрет «»/— во ВСЕХ 9 user-facing канонах; PREV-слепки (байт-в-байт из HEAD); авто-миграция PG-канонов (`services/prompt_migrations.py`, замена `migrate_direct_chat_prompt_if_legacy`). `EXTRACT_PROMPT` и фразы-пулы НЕ трогаем.

### Сценарии пользователя

- Владелец вставляет в панель/чат вопросы про историю конфы — ответ модели знает лор (пермская, джаббер-корни, список людей), не называет конфу екатеринбургской.
- Владелец смотрит журнал после старта с битым токеном — видит WARNING «токен похож на Sentry DSN public key» (до 401) и при 401 подсказку «это должен быть Source Token», не чаще 1/60с.
- Владелец редактирует кастомный промпт в админке — авто-миграция его НЕ трогает (WARNING «кастом юзера — НЕ трогаем»); каноны обновляются автоматически.

### Границы (НЕ ломать)

- `services/betterstack_handler.py` (буфер/флашер/фрейм/close) и интеграция `bot.py:110-149` не переделываются — только добавление чистых функций и текстов WARNING/INFO.
- Память остаётся на SQLite (Epic 86 заморожен; секция E задач).
- Чтение токена — строго `.env` через `os.getenv`; никаких новых источников.
- `EXTRACT_PROMPT` (ETL-экстрактор), `CHECKUP_FALLBACK_NOTICE`, `_RERANK`-подобные, фразы-пулы, `DEFAULT_INFO_TEXT` — не входят в правки.
- Канон-доки `plans/docs/canon/*` — эталоны; правка = атомарный коммит «слепки → константы → эталоны → тесты» (дисциплина байт-в-байт).
- Порядок регистрации роутеров и формат VERBATIM карточек `/persona` (66.9) не меняются.

## 2. Требования (Requirements)

### 2.1 Функциональные — Часть B (BetterStack, T-727..T-730)

- **FR-B1 (T-727)**: чистая функция `looks_like_sentry_public_key(token, dsn) -> bool` в `services/betterstack_handler.py`; при старте (после подключения log_ring, до attached-маркера) при `betterstack_token` и совпадении — WARNING «токен похож на Sentry DSN public key…». Источник токена/`.env` не меняется.
- **FR-B2 (T-728)**: маркер attached содержит имя переменной-источника: `[betterstack] attached | token_len=%d | handler=own-v1 | from=%s` (from ∈ {BETTERSTACK_SOURCE_TOKEN, LOGTAIL_SOURCE_TOKEN}, не значение — R17). Ветка без токена без изменений.
- **FR-B3 (T-729)**: при `status=401` текст WARNING дополняется подсказкой (Source Token из Logs → Sources, не Sentry DSN public key); rate-gate `_rate_warn` ≤1/60с сохраняется; остальные причины (429/5xx/транспорт) — без изменений.
- **FR-B4 (T-730)**: тесты Части B (см. 5).

### 2.2 Функциональные — Часть C (лор, T-731..T-734)

- **FR-C1 (T-731)**: миграция v6 `services/database.py`: `_SCHEMA_VERSION_CHAT_PROTECTED_FACTS = 6`, `_migrate_chat_protected_facts_v6()` по паттерну `_migrate_user_memory_v5` — protected_facts: `user_name` nullable + сохранение `UNIQUE (chat_id, user_name, fact)` + частичный уникальный индекс чат-уровня; вызов в цепочке `initialize()` после v5; повторный запуск — no-op.
- **FR-C2 (T-732, дельта 4.6.2)**: `get_protected_facts(chat_id, user_name, include_chat_level=True)` — чат-уровневые (`user_name IS NULL`) первыми; `<protected_facts>`-блок direct-ответов получает их ВСЕГДА (все юзеры чата); persona-карточка `/persona` тоже включает чат-лор (решение владельца «уместно: лор чата в карточке»).
- **FR-C3 (T-733, дельта 4.6.3)**: новый `services/chat_lore.py`: `CHAT_LORE_TARGET_CHAT_ID = 2661910336`, константа `CHAT_LORE_2661910336` (ДОСЛОВНЫЙ текст юзера — Приложение A), `async ensure_chat_lore(db) -> dict` — идемпотентный инжект protected (chat-level) + graph_facts (`origin='user_memory'`, вечно) + FTS; fail-open; вызов при старте бота (on_startup) + DevOps-скрипт (T-743).
- **FR-C4 (T-734)**: тесты Части C (см. 5), включая дельту persona.

### 2.3 Функциональные — Часть D (промпты, T-735..T-741)

- **FR-D1 (T-735..T-738)**: слепки HEAD в `PREV_*`; правки канонов по таблице Приложения B (байт-в-байт);
- **FR-D2 (T-739)**: канон-эталоны `plans/docs/canon/*` обновлены + добавлены недостающие блоки (direct_chat current/PREV/LEGACY, YOUTUBE_VIDEO, COMPRESS); перечень «Каноны НЕ трогать» в `plans/project.md:37-45` актуализирован.
- **FR-D3 (T-740)**: `services/prompt_migrations.py` — `PROMPT_MIGRATIONS` (9 ключей; direct_chat — двумя ступенями LEGACY→new и PREV→new) + `async migrate_prompt_canons(cache) -> dict[str, str]`; bot.py:595-599 заменяется на вызов `migrate_prompt_canons(cache)` сразу после `cache.init()`; `migrate_direct_chat_prompt_if_legacy` удаляется (chat_prompts.py + bot.py + тесты).
- **FR-D4 (T-741)**: тесты Части D (см. 5).

### 2.4 Часть E (T-742) и Часть F (T-743..T-746)

- E — backlog-пометка Epic 86: выполнено при планировании (T-742 [x]). Ничего не делаем.
- F — DevOps: лор-инжект в прод (T-743), чистка противоречащих фактов (T-744), деплой+live-проверки (T-745), отчёт юзеру с инструкцией по токену (T-746; эталон текста — Приложение C).

### 2.5 Нефункциональные

- R17: реальные токены/значения НЕ в логах и НЕ в коммитах — только `token_len`, имя переменной, слово-подсказка; grep-проверка перед коммитом.
- Байт-в-байт дисциплина канонов (эталон = код = тесты одним коммитом; `git diff --check` чист).
- Полный pytest зелёный (3794 на базе + новые/изменённые).
- Идемпотентность: миграция v6, `ensure_chat_lore`, `migrate_prompt_canons`, `PRAGMA user_version=6`.
- Fail-open: лор-инжект не роняет старт бота; PG down не роняет миграцию промптов.

## 3. Технический дизайн

### 3.1 BetterStack: эвристики и диагностика 401 (Часть B)

#### 3.1.1 FR-B1: стартовая эвристика Sentry DSN (T-727)

В `services/betterstack_handler.py` (модуль уже импортирует os) добавить чистую функцию:

```python
def looks_like_sentry_public_key(token: str, sentry_dsn: str) -> bool:
    """Токен — это public key из Sentry DSN (значение между https:// и @),
    а не Source Token из BetterStack → Logs → Sources. Пустые входы → False."""
    if not token or not sentry_dsn:
        return False
    return f"https://{token}@" in sentry_dsn
```

В `bot.py`: вызов — в блоке стартовой диагностики, ПОСЛЕ подключения log_ring (:136-138) и ДО существующего attached/skipped (:145-149) (logger и log_ring на этом этапе уже есть; sentry_dsn — модульная переменная :24; конструктор хендлера :118-120 не трогаем):

```python
if betterstack_token and looks_like_sentry_public_key(
        betterstack_token, sentry_dsn):
    logger.warning(
        "[betterstack] токен похож на Sentry DSN public key, а не на "
        "Source Token из Logs → Sources — см. отчёт юзера раунда 5")
```

#### 3.1.2 FR-B2: attached-маркер с источником (T-728)

В `services/betterstack_handler.py` — чистая функция выбора имени переменной (зеркалит семантику `or` в bot.py:115-116):

```python
def betterstack_source_env_name(better_var: str | None,
                                logtail_var: str | None) -> str | None:
    """Имя env-переменной, реально давшей токен (R17: имя, не значение).
    BETTERSTACK_SOURCE_TOKEN приоритетнее; иначе LOGTAIL_SOURCE_TOKEN;
    пустые значения игнорируются (как `or` при чтении)."""
    if better_var:
        return "BETTERSTACK_SOURCE_TOKEN"
    if logtail_var:
        return "LOGTAIL_SOURCE_TOKEN"
    return None
```

В `bot.py` заменить блок :145-149:

```python
bs_from = betterstack_source_env_name(
    os.getenv("BETTERSTACK_SOURCE_TOKEN"),
    os.getenv("LOGTAIL_SOURCE_TOKEN"))
if bs_from:
    logger.info("[betterstack] attached | token_len=%d | handler=own-v1 | from=%s",
                len(betterstack_token), bs_from)
else:
    logger.warning("[betterstack] skipped (no BETTERSTACK_SOURCE_TOKEN)")
```

(Ветка `else` — текст без изменений, как сейчас :149.)

#### 3.1.3 FR-B3: подсказка при 401 (T-729)

Rate-gate и формат журнала сбоя сохраняются (`_rate_warn`, ≤1/60с, анти-спам). Текстовое обогащение — в `_mark_failed` (единая точка: сюда приходят все причины, включая `status=401` из `_post` и `_reason`):

```python
_HINT_401 = ("подсказка: проверьте BETTERSTACK_SOURCE_TOKEN/.env — это должен "
             "быть Source Token (BetterStack → Logs → Sources), "
             "а не Sentry DSN public key")

def _mark_failed(self, reason: str, n: int) -> None:
    if reason == "status=401":
        reason = f"status=401 | {_HINT_401}"
    with self._lock:
        self.failed += n
        self._fail_streak += 1
    self._rate_warn(reason)
```

Результирующая строка журнала: `[betterstack] send failed | reason=status=401 | подсказка: проверьте BETTERSTACK_SOURCE_TOKEN/.env — это должен быть Source Token (BetterStack → Logs → Sources), а не Sentry DSN public key | failed=N`. Токен/URL в текст НЕ попадают (R17; `_url` не логируется). 429/5xx/transport — поведение не меняется (ретрай 5xx один раз, 4xx — нет).

### 3.2 Лор-инжект: миграция v6 + семантика чат-уровневых фактов (Часть C)

#### 3.2.1 FR-C1: миграция v6 (T-731)

`services/database.py`:

```python
_SCHEMA_VERSION_CHAT_PROTECTED_FACTS = 6  # Раунд 5 (T-731): user_version 5→6
```

Добавить в цепочку `initialize()` (:220, сразу после v5):

```python
await self._migrate_chat_protected_facts_v6()  # Раунд 5 (T-731): 5→6
```

Метод — точная копия структуры `_migrate_user_memory_v5` (:463-508; пересоздание с сохранением id — прецедент D201):

- **guard**: `SELECT sql FROM sqlite_master WHERE type='table' AND name='protected_facts'`; если sql существует и содержит `"user_name TEXT NOT NULL"` → rebuild + `logger.info("[database] migration v6: protected_facts rebuild (chat-level user_name NULL)")`.
- **rebuild** одним `executescript`:

```sql
ALTER TABLE protected_facts RENAME TO protected_facts_old;
CREATE TABLE protected_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    user_name TEXT,                     -- NULL = чат-уровневый факт (лор чата)
    fact TEXT NOT NULL,
    created_at REAL NOT NULL,
    UNIQUE (chat_id, user_name, fact));
CREATE UNIQUE INDEX IF NOT EXISTS idx_protected_facts_chat_level
    ON protected_facts(chat_id, fact) WHERE user_name IS NULL;
INSERT INTO protected_facts (id, chat_id, user_name, fact, created_at)
    SELECT id, chat_id, user_name, fact, created_at FROM protected_facts_old;
DROP TABLE protected_facts_old;
```

  - Почему partial index: в SQLite `NULL != NULL`, UNIQUE(chat_id, user_name, fact) НЕ защищает от дублей чат-уровневых строк; `idx_protected_facts_chat_level` гарантирует 1 лор на (чат, текст).
  - Старые данные — только именованные (`user_name NOT NULL`) → конфликтов при INSERT…SELECT нет; id сохраняются (FTS/ссылки не затронуты — protected_facts_fts не существует).
- `PRAGMA user_version = 6` + commit — БЕЗУСЛОВНО после guard-блока (паттерн v5: :506-508; повторный запуск: sql уже `user_name TEXT` без NOT NULL → guard false → только PRAGMA=6, no-op).
- CREATE в `_migrate_epic60_v3` (:383-386) НЕ меняем (свежая БД проходит v3→v6 по цепочке; rebuild пустой таблицы — дешёвый).

#### 3.2.2 FR-C2: get_protected_facts с include_chat_level (T-732 + дельта)

`services/database.py:1343-1351`:

```python
async def get_protected_facts(self, chat_id: int, user_name: str,
                              include_chat_level: bool = True) -> list[str]:
    """65.10: защищённые факты юзера. include_chat_level=True (default,
    раунд 5): + чат-уровневые факты (user_name IS NULL — «лор чата»),
    они идут ПЕРВЫМИ (не тонут при обрезке блока). False — старое
    поведение (только user_name = ?). Порядок: чат-уровневые → ASC по
    created_at, id."""
    if include_chat_level:
        cursor = await self.db.execute(
            "SELECT fact FROM protected_facts "
            "WHERE chat_id = ? AND (user_name = ? OR user_name IS NULL) "
            "ORDER BY (user_name IS NULL) DESC, created_at ASC, id ASC",
            (chat_id, user_name))
    else:
        cursor = await self.db.execute(
            "SELECT fact FROM protected_facts "
            "WHERE chat_id = ? AND user_name = ? "
            "ORDER BY created_at ASC, id ASC",
            (chat_id, user_name))
    return [row["fact"] for row in await cursor.fetchall()]
```

`direct_chat_service.py`:
- `:629` `_build_protected_facts` — передать `include_chat_level=True` (значение default; явный параметр + комментарий «чат-лор виден всем юзерам чата ВСЕГДА (65.10+раунд 5)»). Рендер блока :625-638 и escape_xml_text НЕ меняются; блок protected не урезается бюджетами (66.12) — лор не обрезается.
- `:771` `build_persona_card` — `include_chat_level=True` (дельту см. 4.6.2). Шапка карточки и формат VERBATIM (66.9) НЕ меняются: чат-лор появляется первыми строками списка (`lines = list(protected) + list(facts)`), счётчик `n = len(facts) + len(protected)` включает его (одна строка на чат — приемлемо).

`is_fact_protected` (:1673-1679) — уже по `chat_id` + `fact` (без user_name) — **не трогаем** (защита распространяется и на чат-уровневые).

#### 3.2.3 FR-C3: services/chat_lore.py (T-733 + дельта)

Новый модуль `services/chat_lore.py`:

```python
"""Раунд 5 (T-733): лор конференции чата 2661910336 (джаббер-конфа «с нулевых»,
Пермь; переезды ВК→ТГ). Инжект идемпотентный: protected_facts (чат-уровень,
user_name NULL — виден всем юзерам чата в <protected_facts>) + graph_facts
(origin='user_memory', вечно; FTS-строка пишется insert_graph_fact; vec-строка
добирается ленивым backfill при старте). Дата: 04.09.2026."""

import logging
import time

from services.database import DatabaseService

logger = logging.getLogger(__name__)

CHAT_LORE_TARGET_CHAT_ID = 2661910336

# ДОСЛОВНЫЙ текст юзера (04.09.2026, раунд 5, пункт 2) — НЕ редактировать:
CHAT_LORE_2661910336 = ("""<текст из Приложения A — байт-в-байт>""")

async def ensure_chat_lore(db: DatabaseService) -> dict:
    ...
```

`ensure_chat_lore(db) -> dict`:
1. `text = CHAT_LORE_2661910336`, `chat_id = CHAT_LORE_TARGET_CHAT_ID`.
2. protected: `SELECT 1 FROM protected_facts WHERE chat_id=? AND user_name IS NULL AND fact=? LIMIT 1` → нет: `INSERT INTO protected_facts (chat_id, user_name, fact, created_at) VALUES (?, NULL, ?, ?)` (created_at = `time.time()`; частичный индекс защищает от дублей даже при гонке — `INSERT OR IGNORE` допустим).
3. graph_facts: `SELECT 1 FROM graph_facts WHERE chat_id=? AND fact=? AND origin='user_memory' LIMIT 1` → нет: `await db.insert_graph_fact(chat_id, text, "user_memory", expires_at=None, target_user=None, weight=1.0)` (insert_graph_fact сам пишет FTS-строку `graph_facts_fts` и commit; статус default 'confirmed'; vec-эмбеддинг НЕ здесь — его доберёт существующий ленивый backfill при старте).
4. Логи: `logger.info("[chat_lore] ensure | chat_id=%s | inserted=%d | skipped=%d", ...)`.
5. Возврат `{"inserted": n, "skipped": n}` (n — суммарные строки, 0..2).
6. Fail-open: любая ошибка БД → `logger.warning("[chat_lore] ensure failed — fail-open | chat_id=%s", ..., exc_info=True)` и возврат `{"inserted": 0, "skipped": 0}` (старт бота не роняем).

Проверка существования — **по точному тексту факта** (а не по числу строк): частичный/старый инжект с тем же текстом → skip; другой текст лора при обновлении → новая строка (пересоздание лора — ручная операция, вне этого раунда).

**Вызов при старте (дельта 4.6.3)**: в `bot.py` `on_startup()` сразу после `db.initialize()` и лога «Database initialized» (:188-189), до остальной инициализации:

```python
from services.chat_lore import ensure_chat_lore
try:
    result = await ensure_chat_lore(db)
    logger.info("[chat_lore] startup ensure | %s", result)
except Exception:  # fail-open: старт не роняем
    logger.warning("[chat_lore] startup ensure failed", exc_info=True)
```

(Миграция v6 уже применена в `db.initialize()` — инжект после неё безопасен. На проде это «вторая гарантия»: первичный инжект делает @DevOps скриптом T-743 до рестарта; при старте бота строка появится/пропустится идемпотентно.)

#### 3.2.4 Чистка противоречий на проде (T-744) — критерии

Критерии ручного разбора для @DevOps (в spec фиксируются; массовых слепых DELETE не делать):

1. Бэкап: копия `local_database.db` с датой вне репозитория (перед любыми изменениями).
2. Поиск в чате 2661910336 (регистронезависимо, все origin + protected_facts):

```sql
SELECT id, chat_id, fact, origin, weight, status FROM graph_facts
WHERE chat_id = 2661910336
  AND (fact LIKE '%екатеринбург%' COLLATE NOCASE
    OR fact LIKE '%екб%' COLLATE NOCASE
    OR fact LIKE '%уральск%' COLLATE NOCASE)
ORDER BY id LIMIT 20;
SELECT id, chat_id, user_name, fact FROM protected_facts
WHERE chat_id = 2661910336
  AND (fact LIKE '%екатеринбург%' COLLATE NOCASE
    OR fact LIKE '%екб%' COLLATE NOCASE
    OR fact LIKE '%уральск%' COLLATE NOCASE);
```

3. **Удалять/понижать ТОЛЬКО факты, которые по смыслу про КОНФУ/ЧАТ/ИСТОРИЮ** («конфа екатеринбургская», «чат из Екб», «конференция про Екатеринбург», «история чата… Екатеринбург»). Факты про ЛЮДЕЙ (живёт/учился/работает/был в Екатеринбурге, «екб-митап») — НЕ трогать (осторожность: слово может быть про других людей).
4. Удаление — полное, через существующий путь `DatabaseService.delete_graph_fact(fact_id)` (database.py:1659 — graph_facts_fts + vec + graph_facts) или эквивалентными SQL с ручным удалением FTS-строки; перед удалением — запись в `graph_fact_compressions` (`chat_id, fact_id, fact_before=<текст>, fact_after=NULL, reason='lore_cleanup_round5', created_at`). Альтернатива вместо удаления — понижение: `weight = 0.1` + запись в compressions (`fact_after` = факт, `reason='lore_cleanup_round5'`).
5. Отчёт по каждой строке (найдено → действие → причина) — в F4.

### 3.3 Промпты: правки канонов + PREV-слепки + миграции (Часть D)

#### 3.3.1 Дисциплина и порядок (CRITICAL для @Builder)

1. **Сначала слепки**: в каждом модуле до правки зафиксировать ТЕКУЩИЕ константы HEAD (68fb03e) как `PREV_*` (комментарий «слепок HEAD 68fb03e (раунд 5) ДО правки — для авто-миграции PG»). Прецедент: LEGACY_CHAT_SYSTEM_PROMPT в chat_prompts.py.
2. Потом править каноны строго по таблице Приложения B (байт-в-байт; копировать из таблицы/констант, не перепечатывать).
3. Канон-эталоны (T-739) — после правки констант: блоки в `plans/docs/canon/*` обновляются ДОСЛОВНО из констант; недостающие блоки добавляются по существующему формату.
4. Тесты — в том же коммите (эталон + код + тесты одним атомарным коммитом).

#### 3.3.2 Единые эталонные формулировки

- **TYPO** (запрет «»/—), полная строка:

```
Типографика: только короткие дефисы (-) и обычные двойные кавычки (""). КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНЫ длинные тире (—) и кавычки-елочки («»).
```

- **CASING** (замена «имитации»), база: `Имитируй торопливое письмо: иногда начинай предложения с маленькой буквы.`
  - chat-вариант: `1. Имитируй торопливое письмо: иногда начинай предложения с маленькой буквы. Без форматирования (никакого маркдауна).`
  - summary-вариант: `1. Имитируй торопливое письмо: иногда начинай предложения с маленькой буквы. Текст должен быть читаемым, но выглядеть небрежно.`
  - кластер-вариант (checkup/factcheck/search/youtube/web): `1. Имитируй торопливое письмо: иногда начинай предложения с маленькой буквы. Пиши небрежно.`
  - compress-вариант (строчный стиль): `не используй нумерацию, маркдаун, смайлы, кавычки-елочки («») и длинные тире (—). иногда начинай предложения с маленькой буквы, имитируя торопливое письмо.`

#### 3.3.3 Файлы и правки (карта)

| Файл | Константы | Действие |
|---|---|---|
| `services/chat_prompts.py` | LEGACY (не трогать); CHAT_SYSTEM_PROMPT → правка п.1/п.2; **+ PREV_CHAT_SYSTEM_PROMPT** (= CHAT_SYSTEM_PROMPT HEAD); удалить `migrate_direct_chat_prompt_if_legacy` (:47-66) и `_PROMPT_KEY`-зависимую часть (переносится в prompt_migrations) | T-735 |
| `services/summary_prompts.py` | **+ PREV_SUMMARY_SYSTEM_PROMPT, PREV_COMPRESS_PROMPT**; SYSTEM_PROMPT → п.1 + новый п.7 TYPO; COMPRESS_PROMPT → фрагмент; EXTRACT_PROMPT НЕ трогать | T-736 |
| `services/checkup_prompts.py` | **+ PREV_CHECKUP_SYSTEM_PROMPT**; п.1; п.3 — байт-сверка | T-737 |
| `services/factcheck_prompts.py` | **+ PREV_FACTCHECK_SYSTEM_PROMPT**; п.1; п.3 — байт-сверка | T-737 |
| `services/search_prompts.py` | **+ PREV_SEARCH_SYSTEM_PROMPT**; п.1; п.3 — байт-сверка | T-738 |
| `services/youtube_prompts.py` | **+ PREV_YOUTUBE_SYSTEM_PROMPT, PREV_YOUTUBE_VIDEO_SYSTEM_PROMPT**; п.1 обеих; п.3 — байт-сверка | T-738 |
| `services/web_prompts.py` | **+ PREV_WEBPAGE_SYSTEM_PROMPT**; п.1; п.3 — байт-сверка | T-738 |

Точные OLD→NEW для каждой константы — **Приложение B** (критично: полные строки/фрагменты, байт-в-байт).

#### 3.3.4 services/prompt_migrations.py (НОВЫЙ, T-740)

```python
PROMPT_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "prompts.direct_chat_system_prompt": [
        (LEGACY_CHAT_SYSTEM_PROMPT, CHAT_SYSTEM_PROMPT),
        (PREV_CHAT_SYSTEM_PROMPT, CHAT_SYSTEM_PROMPT)],
    "prompts.summary_system_prompt": [(PREV_SUMMARY_SYSTEM_PROMPT, SYSTEM_PROMPT)],
    "prompts.compress_system_prompt": [(PREV_COMPRESS_PROMPT, COMPRESS_PROMPT)],
    "prompts.checkup_system_prompt": [(PREV_CHECKUP_SYSTEM_PROMPT, CHECKUP_SYSTEM_PROMPT)],
    "prompts.factcheck_system_prompt": [(PREV_FACTCHECK_SYSTEM_PROMPT, FACTCHECK_SYSTEM_PROMPT)],
    "prompts.search_system_prompt": [(PREV_SEARCH_SYSTEM_PROMPT, SEARCH_SYSTEM_PROMPT)],
    "prompts.youtube_system_prompt": [(PREV_YOUTUBE_SYSTEM_PROMPT, YOUTUBE_SYSTEM_PROMPT)],
    "prompts.youtube_video_system_prompt": [(PREV_YOUTUBE_VIDEO_SYSTEM_PROMPT, YOUTUBE_VIDEO_SYSTEM_PROMPT)],
    "prompts.webpage_system_prompt": [(PREV_WEBPAGE_SYSTEM_PROMPT, WEBPAGE_SYSTEM_PROMPT)],
}
# prompts.extract_system_prompt НЕ входит (EXTRACT_PROMPT не трогаем)
```

`async def migrate_prompt_canons(cache) -> dict[str, str]` — семантика (прецедент migrate_direct_chat_prompt_if_legacy, лог-маркер `[prompt_migration]`):

- `cache is None or not cache.pg_available` → INFO `[prompt_migration] skip: PG недоступен`, возврат `{}`.
- Итерация по ключам в ФИКСИРОВАННОМ порядке объявления словаря (детерминированный порядок/тесты). Для каждого ключа `current = cache.get(key)`:
  - `current is None` → INFO `[prompt_migration] ключ отсутствует — сид сделает своё | key=…` (skip).
  - `current == new` (любой new из ступеней) → skip (INFO «уже новый канон | key=…»).
  - `current == prev` (первая совпавшая ступень из списка; direct_chat — LEGACY или PREV) → `await cache.set(key, new, "prompts")` + INFO `[prompt_migration] канон обновлён | key=…`; в отчёт `report[key] = "updated"`.
  - иначе (custom) → WARNING `[prompt_migration] кастом юзера — НЕ трогаем | key=… | chars=N` (skip).
- Возврат отчёта `dict[str, str]` обновлённых ключей (пусто — ничего не обновлено).

bot.py: заменить :595-599:

```python
# ── Раунд 5 (T-740): авто-миграция канонов промптов в PG (9 ключей;
# канон → новый канон; кастом юзера НЕ трогаем; PG down / ключ отсутствует →
# skip с логом [prompt_migration]). Заменяет migrate_direct_chat_prompt_if_legacy.
from services.prompt_migrations import migrate_prompt_canons
await migrate_prompt_canons(cache)
```

`migrate_direct_chat_prompt_if_legacy` удаляется из `services/chat_prompts.py`; все импорты/вызовы: bot.py (:598-599) и `tests/test_direct_chat_prompts.py` (:15, класс TestPromptMigration :164-198) — переносятся на `migrate_prompt_canons`. Docstring-ссылка в `summary_memory.py:425` — комментарий, допустимо обновить косметически.

Замечание: runtime-чтение промптов — `hot.get(key, константа)` (direct_chat_service.py:314, summary_generator.py:168, checkup/factcheck/search/youtube/web-сервисы) — после правки констант дефолты обновляются автоматически, PG-значения обновит миграция.

#### 3.3.5 Канон-эталоны и project.md (T-739)

- `plans/docs/canon/backlog.md`: R11 v4 summary SYSTEM_PROMPT — блок «### Системный промпт (R11…» (строки ~5-32) обновить до нового текста (п.1 + п.7 TYPO; RAG-инструкция вне фенса остаётся); R42-6 CHECKUP — таблица-строка (~:36, литеральные `\n`) обновить до нового п.1 (п.3 TYPO уже совпадает); ДОБАВИТЬ: `COMPRESS_PROMPT`-блок (по формату code-fence, как R11) — дословно из константы.
- `plans/docs/canon/architecture.md`: обновить блоки CHECKUP (~19-38), SEARCH (~46-69), YOUTUBE (~73-91), WEBPAGE (~95-113), FACTCHECK (Section 72, text-fence ~115-146) — только строка п.1 в каждом; ДОБАВИТЬ блоки `YOUTUBE_VIDEO_SYSTEM_PROMPT` и `CHAT_SYSTEM_PROMPT` (текущий канон) + `PREV_CHAT_SYSTEM_PROMPT` + `LEGACY_CHAT_SYSTEM_PROMPT` по формату существующих (`NAME = """…"""` + шапка-происхождение). Источник — константы кода ПОСЛЕ T-735/T-736/T-738.
- `plans/project.md:37-45`: актуализировать перечень «Каноны НЕ трогать» (добавить новые блоки/источники), если менялись источники.
- Дипломатия байт-в-байт: новые тесты-эталоны читают canon-файлы по якорям (см. 5.3) — текст в canon должен БАЙТ-В-БАЙТ равняться константам.

### 3.4 Файлы-кандидаты изменений

| Файл | Изменение |
|---|---|
| `services/betterstack_handler.py` | + `looks_like_sentry_public_key`, `betterstack_source_env_name`, 401-hint в `_mark_failed` |
| `bot.py` | эвристика + from-маркер (:138-149); миграция промптов (:595-599); `ensure_chat_lore` в on_startup (:188-189) |
| `services/database.py` | v6-миграция, `get_protected_facts(include_chat_level)` |
| `services/direct_chat_service.py` | :629 и :771 — include_chat_level=True |
| `services/chat_lore.py` | НОВЫЙ |
| `services/prompt_migrations.py` | НОВЫЙ |
| `services/chat_prompts.py` | PREV_*, правки, удаление migrate-функции |
| `services/summary_prompts.py`, `checkup_prompts.py`, `factcheck_prompts.py`, `search_prompts.py`, `youtube_prompts.py`, `web_prompts.py` | PREV_*, правки |
| `plans/docs/canon/backlog.md`, `plans/docs/canon/architecture.md`, `plans/project.md` | эталоны |
| `tests/` | T-730/T-734/T-741 + перевод тестов миграции |

## 4. Пограничные случаи и решения (Edge cases)

### 4.1 BetterStack

- **401 против 429/5xx**: 401 — битый токен (не ретраится, hint); 429/5xx — транзиентные (один ретрай, как сейчас). Hint применяется только при точном `reason == "status=401"` (включая путь `_reason` для HTTPError с code 401 — он уже даёт `status=401`).
- **Пустые/ложные входы эвристики**: `looks_like_sentry_public_key("", dsn)`, `("tok", "")`, и DSN с другим токеном → False; при нескольких `@` в DSN — substring-матч `https://{token}@` достаточен (R17: значение токена в лог не попадает, только факт WARNING).
- **Обе переменные пусты** — `betterstack_token` пуст → ветка `else` (текст без изменений), эвристика не срабатывает (guard `if betterstack_token and …`).
- **Rate-limit**: серия 401 → одно WARNING в окне 60с (`_last_warn_ts` сохраняется); тест это проверяет.
- **Ручная правка .env токена** — код не меняется, только диагностика (граница: «код по токенам больше не меняем»).

### 4.2 Лор и миграция v6

- **SQLite NULL-UNIQUE**: `UNIQUE(chat_id, user_name, fact)` НЕ блокирует дубли чат-уровневых строк (NULL != NULL) → обязателен частичный уникальный индекс; он же — защита при гонке двух ensure.
- **Повторный запуск миграции**: guard по `sqlite_master` sql + безусловный `PRAGMA user_version = 6` (паттерн v4/v5). Свежая БД: v3 создаёт NOT NULL-таблицу, v6 пересоздаёт (пустая — дёшево).
- **Лор в persona**: карточка — «факты о тебе», но владелец решил чат-лор включать («уместно: лор чата в карточке»; 4.6.2). Шапка/формат 66.9 VERBATIM не меняются; лор — первая строка списка; доступ к чужим карточкам и так ограничен (persona_access, ADMIN_USER_ID).
- **Idempotency ensure**: проверка по точному тексту; при частичном успехе (вставлен protected, graph уже был) повторный запуск доснимает недостающее (skipped/inserted считаются отдельно). Ошибка БД → fail-open + WARNING (бот живёт).
- **vec-строка**: `insert_graph_fact` не пишет эмбеддинг — его добирает существующий ленивый backfill при старте (прецедент раунда 4, user_memory); FTS-строка пишется всегда (внутри insert_graph_fact).
- **Чистка (T-744)**: только факты про конфу/чат/историю, НЕ про людей; бэкап обязателен; ручной просмотр каждого (до 20); причина в compressions `lore_cleanup_round5`.
- **ensure при SUMMARY_ENABLED=False**: db.initialize() и ensure — БЕЗУСЛОВНЫ (вне summary-гейта :239) → лор ставится при любом флаге.
- **Текст лора**: содержит «ее»/без ё, `(тм)`, скобки — только дословный текст (Приложение A); НЕ выдумывать/перефразировать; если у @Builder в контексте полного текста нет — ⏸ до получения от юзера (в spec текст есть, Приложение A).

### 4.3 Промпты

- **Прод-значения PG могут отстать на канон раунда-2 (LEGACY) или раунда-4 (PREV)** — direct_chat мигрирует двумя ступенями; иначе custom → WARNING.
- **«Уже новый канон»** (повторный старт) → no-op (INFO). **PG down** → INFO skip (R6: бот работает на дефолтах констант — они уже новые).
- **Кастом юзера**, байт-совпадающий со старым каноном: с точки зрения миграции он == prev → обновится (это и есть цель: прод-значение «канон» обновляется; осознанно отредактированный текст канона неотличим — приемлемо, прецедент раунда 4).
- **Нумерация summary**: новый пункт — «7.» (следующий свободный; без перенумерации). Тест `test_numbering_sequential` (assert «7. » отсутствует в блоке ПРАВИЛ) — ОБНОВИТЬ (теперь «7.» присутствует).
- **COMPRESS**: стиль строчный — клауза в нижнем регистре, это НЕ нарушение TYPO-эталона (иной регистр, но тот же смысл; тест — по словам «кавычки-елочки («»)»/«длинные тире (—)»).
- **EXTRACT_PROMPT и его PG-ключ** `prompts.extract_system_prompt` — НЕ входит в PROMPT_MIGRATIONS и не правится (ETL, не user-facing); canon-блок EXTRACT не меняется.
- **Порядок итерации** миграции — фиксированный (порядок объявления словаря) → детерминированные логи/тесты.
- **Баланс «канон в коде == канон в PG-сиде»**: сид ставит новые константы для отсутствующих ключей (ничего не меняем); миграция покрывает существующие значения.

### 4.4 Тесты-ловушки существующих ожиданий (обновить в T-741)

- test_direct_chat_prompts: канон-эталоны, LEGACY не меняется, класс TestPromptMigration → на prompt_migrations.
- test_summary_prompts: `test_numbering_sequential` (п.7), `test_rule_3_typography_removed` («3. Типографика» — отсутствует; добавление «7. Типографика» не ломает), COMPRESS-фразы («пиши с маленькой буквы» — больше нет; «с маленькой буквы» тоже исчезает из COMPRESS — проверить все asserts на эту подстроку).
- test_checkup_prompts / test_factcheck_prompts / test_smartsearch_prompts: канон-эталоны п.1.
- test_betterstack_handler (15 регресс) — расширяется (T-730).
- test_database / test_graphrag_database: цепочка миграций user_version → 6; protected_facts-тесты.

### 4.5 Открытые вопросы (решаются в раунде)

- Нет. Все вопросы закрыты: persona-решение и вызов ensure — см. 4.6; текст лора — Приложение A.

### 4.6 Дельта дизайна относительно tasks.md (переопределения для @Builder)

Диагностика после планирования уточнила 3 решения; tasks.md остаётся чеклистом, **формулировки ниже — приоритетнее**:

1. **spec.md создаётся** (tasks.md A: «spec.md НЕ создаётся» — отменено решением владельца; этот файл).
2. **T-732 persona-карточка**: «— False (чат-лор в карточки и счётчик N не попадает)» → **включаем** чат-уровневые protected в `build_persona_card` (`include_chat_level=True`): «уместно: лор чата в карточке». Следствие для T-734: тест «persona-карточка НЕ содержит чат-лор» заменяется на «persona-карточка содержит чат-лор первой строкой списка (при вставленном лоре), шапка/N-формат не меняются».
3. **T-733 «Не вызывать из бота автоматически»** → **вызываем**: `ensure_chat_lore(db)` в `bot.py on_startup()` после `db.initialize()` (гарантия при каждом старте; DevOps T-743 — первичный инжект; идемпотентность покрывает двойное выполнение). Имя функции в коде — `ensure_chat_lore` (в tasks.md — `inject`; используется имя из дизайна владельца).
4. **T-733 текст лора**: полный дословный текст юзера в контексте планирования ЕСТЬ — Приложение A; задача НЕ в статусе ⏸ (⏸ только если @Builder не скопирует текст из spec).

## 5. Критерии приёмки (Acceptance criteria)

### 5.1 Часть B (T-730)

1. `looks_like_sentry_public_key`: dsn с `https://{token}@` → True; пустой token/dsn, несовпадение → False.
2. `betterstack_source_env_name`: (None,'x') → LOGTAIL_SOURCE_TOKEN; ('x','y') → BETTERSTACK_SOURCE_TOKEN; (None,None) → None; ('','x') → LOGTAIL_SOURCE_TOKEN.
3. attached-маркер при обеих конфигурациях env содержит `from=BETTERSTACK_SOURCE_TOKEN`/`from=LOGTAIL_SOURCE_TOKEN` (проверка формата `[betterstack] attached | token_len=%d | handler=own-v1 | from=%s`).
4. 401 → WARNING содержит слово-подсказку («Source Token», «Sentry DSN») и НЕ содержит значения токена (R17).
5. Серия 401 → одно WARNING в окне 60с (rate-gate жив).
6. Регресс: 15 тестов test_betterstack_handler зелёные.

### 5.2 Часть C (T-734)

1. Миграция v6 на БД с v5-схемой и пер-юзерными protected: данные сохранены (id не изменились); `user_name` nullable; `idx_protected_facts_chat_level` существует (дубль chat-level INSERT падает / OR IGNORE срабатывает); повторный запуск — no-op; `PRAGMA user_version=6`.
2. `get_protected_facts`: include_chat_level=True — чат-факт при ЛЮБОМ user_name + только свои user-факты; False — только user-факты (матрица True/False); чат-факт всегда первый (`ORDER BY`); создание по датам корректно.
3. persona-карточка (build_persona_card с канон-именем): содержит чат-лор первой строкой; шапка/счётчик — формат 66.9; при отсутствии чат-лора — старое поведение.
4. `ensure_chat_lore`: первый вызов — inserted=2 (protected + graph; FTS-строка существует в graph_facts_fts по rowid), повторный — inserted=0/skipped=2 (тот же dict-контракт); `get_protected_facts(2661910336, <любой>)` возвращает лор; CHAT_LORE_2661910336 непуста и содержит ключевые слова («Пермь», «джаббер», «ВК», «телеграм» — из Приложения A).
5. Регресс: test_database/test_graphrag_database/test_epic65-protected-тесты.

### 5.3 Часть D (T-741)

1. **Байт-равенство**: каждый обновлённый канон == соответствующему канон-блоку в `plans/docs/canon/*` (тесты-эталоны по образцу test_direct_chat_prompts/test_summary_prompts/test_checkup_prompts/test_factcheck_prompts/test_smartsearch_prompts; якоря сохранены/обновлены).
2. **PREV_-слепки**: `PREV_* !=` новому канону и содержат старые эталонные фразы: direct_chat — «только строчные буквы (включая начало предложений)»; summary — «чередуй заглавные и строчные» и «Не пиши всё только с маленькой буквы»; compress — «пиши с маленькой буквы»; checkup/factcheck/search/youtube/youtube_video/web — «чередуй заглавные и строчные». LEGACY_CHAT_SYSTEM_PROMPT — байт-неизменен.
3. **Миграция (мок-cache)**: current == prev → set(key, new, "prompts") вызван + INFO; current == LEGACY (direct_chat) → set; current == PREV (direct_chat) → set; current == new → no-op; кастом → skip + WARNING; None → skip; PG down → skip; возврат отчёта.
4. **В промптах**: TYPO-клауза присутствует во всех 9 (полная строка — в 8; compress — фрагмент «кавычки-елочки («») и длинные тире (—)»); CASING-фраза «Имитируй торопливое письмо: иногда начинай предложения с маленькой буквы» во всех 9 (compress — lowercase-вариант); запрещённые старые фразы отсутствуют: «только строчные буквы (включая начало предложений)», «чередуй заглавные и строчные», «Не пиши всё только с маленькой буквы», «пиши с маленькой буквы» (compress). EXTRACT_PROMPT — байт-неизменен.
5. Полный pytest — 0 failed.

### 5.4 Часть F (T-745 live-проверки)

- journald: `[database] migration v6: protected_facts rebuild (chat-level user_name NULL)` (или no-op + `user_version=6`); `[betterstack] attached … | from=…` (+ при битом токене WARNING-подсказка ≤1/60с); `[chat_lore] startup ensure | inserted=…`; `[prompt_migration] канон обновлён | key=…` для всех 9 (или WARNING «кастом»).
- Верификация БД после F1-F2 (protected user_name IS NULL; graph_facts origin='user_memory' weight=1.0 expires_at NULL; fts-rowid; чистота по «екатеринбург»-конфе).
- Живой тест: direct-вопрос в чате про историю конфы — ответ знает лор (не «екатеринбургская»).
- TMA: сохранение кастом-промпта с «»/—/переносами — 200 (миграция не сломала API).

## 6. План миграции/докатки

### Тесты (создать/править)

- `tests/test_betterstack_handler.py`: + B-тесты (5.1); регресс 15 существующих.
- `tests/test_database.py` / `tests/test_graphrag_database.py`: миграция v6 + цепочка user_version (5.2.1).
- `tests/test_direct_chat.py`/`test_memory_*`/прочие protected-тесты: include_chat_level-матрица; persona-дельту (5.2.3).
- `tests/test_chat_lore.py` (новый): ensure-идемпотентность/FTS/лоре-константа.
- `tests/test_direct_chat_prompts.py`: эталоны new/PREV; TestPromptMigration → на `migrate_prompt_canons` (или в новый `tests/test_prompt_migrations.py`).
- `tests/test_summary_prompts.py`, `test_checkup_prompts.py`, `test_factcheck_prompts.py`, `test_smartsearch_prompts.py`: эталоны п.1/numbering/compress (4.4).
- `tests/test_prompt_migrations.py` (новый): кейсы 5.3.3 + отсутствие extract-ключа + фиксированный порядок.

### Документация и деплой (@DevOps)

- Эталоны canon + project.md (T-739); plans/features/betterstack-lore-prompts-round5/ (spec+отчёт); финальный docs(plans)-коммит.
- Прод: `git pull --ff-only` → мягкий рестарт (миграция v6 при старте) → T-743 инжект скриптом (python-инлайн, `asyncio.run(ensure_chat_lore(db))`, DB_PATH прода — local_database.db) → T-744 чистка → live-проверки (5.4) → отчёт T-746 (шаблон — Приложение C).
- Промпты: ничего вручную в PG не менять — авто-миграция при старте; кастом юзера останется (WARNING).

### Каскад развёртывания

1. Код B-D + тесты зелёные локально (полный pytest).
2. Один атомарный коммит «эталоны+код+тесты» (или серия по частям B/C/D с полным pytest перед коммитом), grep-проверка секретов, `git diff --check`.
3. Пуш → прод pull --ff-only → рестарт → T-743/T-744/T-745 → отчёт.

## Приложение A: полный текст лора чата 2661910336 (ДОСЛОВНО, T-733/FR-C3)

Константа `CHAT_LORE_2661910336` в `services/chat_lore.py` = следующий текст БАЙТ-В-БАЙТ (один абзац, без ведущих/хвостовых пробелов; «ее» и «(тм)» — как в оригинале; содержимое НЕ выдумывать и не перефразировать):

```
Эта конфа существует уже много лет и ее история тянется с нулевых, начиная с джаббер конфы, она не раз переезжала, то в ВК, то в телеграм, не раз пересоздавалась. Изначально это Пермская конфа, но исторически сложилось что тут люди из разных городов. Изначально все начиналось со Светы, Максима Гурьева и жаббер конфы, потом сходки соц из Светы, Сокача, Эткина, Светочки, Даши(тм), Жени, Даши, Кирилла, Ринтаро, Коткуна, потом Васи, Ксюши, Леры и закамские сходки, Никита из Анадыря, Саня Карсаков, Абатур, Витя, Врач, Денис (земля ему пухом), Савы, Симкикуна, Артема и так далее. Это очень длинный лор, это знать надо.
```

## Приложение B: таблица правок промптов OLD→NEW (9 канонов, байт-в-байт)

Условные обозначения: **TYPO** = `Типографика: только короткие дефисы (-) и обычные двойные кавычки (""). КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНЫ длинные тире (—) и кавычки-елочки («»).`; **CASING** = `Имитируй торопливое письмо: иногда начинай предложения с маленькой буквы`. Фрагменты — дословно из HEAD (сверено с кодом 05.09.2026). Остальной текст каждой константы — НЕ менять (кроме случаев, отмеченных «+ новая строка»).

| # | PG-ключ / константа (файл) | Где | OLD (HEAD) | NEW |
|---|---|---|---|---|
| 1 | `prompts.direct_chat_system_prompt` / `CHAT_SYSTEM_PROMPT` (chat_prompts.py:30) | п.1 | `1. Имитируй ленивую печать: только строчные буквы (включая начало предложений), без форматирования (никакого маркдауна).` | `1. Имитируй торопливое письмо: иногда начинай предложения с маленькой буквы. Без форматирования (никакого маркдауна).` |
| 1a | то же (chat_prompts.py:31) | п.2 | `2. Пунктуация базовая, без сложных тире.` | `2. Типографика: только короткие дефисы (-) и обычные двойные кавычки (""). КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНЫ длинные тире (—) и кавычки-елочки («»).` |
| 2 | `prompts.summary_system_prompt` / `SYSTEM_PROMPT` (summary_prompts.py:15) | п.1 | `1. Имитируй ленивую печать: чередуй заглавные и строчные буквы в начале предложений случайным образом. Не пиши всё только с маленькой буквы. Текст должен быть читаемым, но выглядеть небрежно.` | `1. Имитируй торопливое письмо: иногда начинай предложения с маленькой буквы. Текст должен быть читаемым, но выглядеть небрежно.` |
| 2a | то же (summary_prompts.py, после п.6, перед блоком ЗАДАЧА) | + новая строка | — (пункта нет) | `7. Типографика: только короткие дефисы (-) и обычные двойные кавычки (""). КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНЫ длинные тире (—) и кавычки-елочки («»).` |
| 3 | `prompts.compress_system_prompt` / `COMPRESS_PROMPT` (summary_prompts.py:35) | фрагмент | `не используй нумерацию, маркдаун и смайлы. пиши с маленькой буквы.` | `не используй нумерацию, маркдаун, смайлы, кавычки-елочки («») и длинные тире (—). иногда начинай предложения с маленькой буквы, имитируя торопливое письмо.` |
| 4 | `prompts.checkup_system_prompt` / `CHECKUP_SYSTEM_PROMPT` (checkup_prompts.py:14) | п.1 | `1. Имитируй ленивую печать: чередуй заглавные и строчные буквы в начале предложений. Пиши небрежно.` | `1. Имитируй торопливое письмо: иногда начинай предложения с маленькой буквы. Пиши небрежно.` |
| 5 | `prompts.factcheck_system_prompt` / `FACTCHECK_SYSTEM_PROMPT` (factcheck_prompts.py:13) | п.1 | `1. Имитируй ленивую печать: чередуй заглавные и строчные буквы в начале предложений. Пиши небрежно.` | `1. Имитируй торопливое письмо: иногда начинай предложения с маленькой буквы. Пиши небрежно.` |
| 6 | `prompts.search_system_prompt` / `SEARCH_SYSTEM_PROMPT` (search_prompts.py:13) | п.1 | `1. Имитируй ленивую печать: чередуй заглавные и строчные буквы в начале предложений. Пиши небрежно.` | `1. Имитируй торопливое письмо: иногда начинай предложения с маленькой буквы. Пиши небрежно.` |
| 7 | `prompts.youtube_system_prompt` / `YOUTUBE_SYSTEM_PROMPT` (youtube_prompts.py:13) | п.1 | `1. Имитируй ленивую печать: чередуй заглавные и строчные буквы в начале предложений. Пиши небрежно.` | `1. Имитируй торопливое письмо: иногда начинай предложения с маленькой буквы. Пиши небрежно.` |
| 8 | `prompts.youtube_video_system_prompt` / `YOUTUBE_VIDEO_SYSTEM_PROMPT` (youtube_prompts.py:37) | п.1 | `1. Имитируй ленивую печать: чередуй заглавные и строчные буквы в начале предложений. Пиши небрежно.` | `1. Имитируй торопливое письмо: иногда начинай предложения с маленькой буквы. Пиши небрежно.` |
| 9 | `prompts.webpage_system_prompt` / `WEBPAGE_SYSTEM_PROMPT` (web_prompts.py:13) | п.1 | `1. Имитируй ленивую печать: чередуй заглавные и строчные буквы в начале предложений. Пиши небрежно.` | `1. Имитируй торопливое письмо: иногда начинай предложения с маленькой буквы. Пиши небрежно.` |

Сверка: п.3 (TYPO) в константах 4-9 уже содержит полную эталонную строку — НЕ менять (байт-сверка). В константе 1 п.3 («Разрешен мат и сленг. Будь грубым, но по факту.») и блок ИНСТРУМЕНТЫ/ГЛАВНОЕ ОГРАНИЧЕНИЕ — не менять. В константе 2 п.2-п.6, ЗАДАЧА/ОГРАНИЧЕНИЕ/ФИНАЛ/`{max_symbols}`/`{username}`/RAG-приписка — не менять. LEGACY_CHAT_SYSTEM_PROMPT, EXTRACT_PROMPT — не менять. PREV_*-константы = байт-слепки констант 1-9 из HEAD (ДО правки).

## Приложение C: шаблон отчёта юзеру (T-746, секция F4)

1. **BetterStack 401 — root cause и инструкция**: в `LOGTAIL_SOURCE_TOKEN` прод-`.env` вставлен public key из SENTRY_DSN (это НЕ Source Token). Шаги: BetterStack → Logs → Sources → создать/взять source «AdminBot» → скопировать Source Token → заменить значение в `/var/www/admin_bot/.env` (переменная `BETTERSTACK_SOURCE_TOKEN`/`LOGTAIL_SOURCE_TOKEN`). ПЕРЕД рестартом curl-тест:

```
curl -s -o /dev/null -w "%{http_code}" -X POST "https://in.logs.betterstack.com/<SOURCE_TOKEN>" -H "Content-Type: application/json" -d '[{"dt":"2026-09-04T12:00:00Z","level":"info","message":"betterstack round5 test"}]'
```

→ ожидание 200/202; затем `systemctl restart admin_bot`; контроль: journald `[betterstack] attached … | from=…` и событие в панели.

2. Итог лор-инжекта (T-743/T-744): inserted/skipped, список удалённых/пониженных фактов (reason `lore_cleanup_round5`), подтверждение, что конфа идентифицируется как пермская.
3. Пункт 3: память остаётся на SQLite, Epic 86 заморожен (T-742).
4. Промпты: стиль «торопливое письмо» + запрет «»/— во всех 9 канонах; PG-каноны обновлены автоматически при старте, кастом не тронут (перечень ключей из отчёта миграции).
