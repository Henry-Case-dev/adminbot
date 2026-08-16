# ARCHITECTURE.md — AdminBot

> **Версия:** v2.25.0 (прод) / целевой дизайн: v2.26.0 (Epic 28)
> **Дата:** 2026-08-16
> **Статус:** Архитектурный контракт. Секции 1–29: дизайн Epic 18–21 (реализованы и задеплоены). Секция 30: дизайн Epic 22 (v2.20.0) — IMPLEMENTED ✅. Секция 31: конвенция media/. Секция 32: дизайн Epic 23 (v2.21.0) — DONE & DEPLOYED ✅ (672 теста; коммит `756d237`, прод v2.21.0, PID 917681). Секция 33: дизайн Epic 24 «SmartModule: Summary» (v2.22.0) — IMPLEMENTED ✅ (T-174…T-189, ревью T-188-D APPROVED, 835 тестов; README обновлён). Секция 34: дизайн Epic 25 (v2.23.0-fix) — IMPLEMENTED ✅ (860 тестов, прод PID 923954). Секция 35: дизайн Epic 26 «GraphRAG» (v2.24.0) — IMPLEMENTED & DEPLOYED ✅ (939 тестов, прод PID 926618). Секция 36: дизайн Epic 27 (v2.25.0) — IMPLEMENTED & DEPLOYED ✅ (коммит `1d7bed4`, 939 тестов, прод PID 934174). Секция 37: дизайн Epic 28 (v2.26.0) — DESIGN (@Architect, шаг 2/3).
> **Chore (2026-08-16):** media-задача — закоммитить и задеплоить `media/common/danger/danger_drone.mp4` (16-й файл danger-пула); конвенция media/ зафиксирована в секции 31.
> **Автор:** @Architect

---

## СОДЕРЖАНИЕ

1. [Задача 1](#1-задача-1--баг-danger_word--forwarded-messages) — Баг `danger` (сервис `common`) и парсинг репостов
2. [Задача 2](#2-задача-2--поломка-репостинга-dead-page) — Поломка репостинга `dead page` (Rich Message)
3. [Задача 3](#3-задача-3--фича-mimic-передразнивание) — Фича `mimic` (передразнивание)
4. [Задача 4](#4-задача-4--смена-путей-slavik-media--рандомный-медиа-пикер) — Смена путей slavik media + рандомный медиа-пикер
5. [Сводный план для Builder](#5-сводный-план-для-builder) — Порядок реализации, риски, тест-план
6. [Приложение A: Текущий Router Order](#приложение-a-текущий-router-order)
7. [Приложение B: Диагностическая SSH-проверка](#приложение-b-диагностическая-ssh-проверка-для-задачи-1)
8. [Section 28: Epic 20](#section-28-epic-20--slavik-random-media-enhancement-v2180) — Slavik Random Media Enhancement (v2.18.0)
9. [Section 29: Epic 21](#29-epic-21--mimic-propagation-fix--time-format-cooldowns) — MIMIC Propagation Fix + Time-Format Cooldowns (v2.19.0)
10. [Section 30: Epic 22](#30-epic-22--гонка-функций-и-точность-триггеров-v2200) — Гонка функций и точность триггеров (v2.20.0, НОВОЕ)
11. [Section 31: Конвенция media/](#31-конвенция-media-2026-08-16) — Политика media/ + инвентарь медиа-пулов (2026-08-16)
12. [Section 32: Epic 23](#32-epic-23--точная-настройка-danger-словаря-v2210) — Точная настройка danger-словаря (v2.21.0, НОВОЕ)
13. [Section 33: Epic 24](#33-epic-24--smartmodule-summary-v2220) — SmartModule: Summary (v2.22.0, НОВОЕ — трёхуровневая память, LLM, APScheduler)
14. [Section 34: Epic 25](#34-epic-25--багфикс-summary-не-реагирует--удаление-команды-v2230) — Багфикс «/summary не реагирует» + удаление команды (v2.23.0)
15. [Section 35: Epic 26](#35-epic-26--graphrag-граф-знаний-поверх-sqlite-v2240) — GraphRAG: граф знаний поверх SQLite (v2.24.0, НОВОЕ)
16. [Section 36: Epic 27](#36-epic-27--новый-system_prompt-бот-абьюзер-v2--summary_aliases-на-прод-v2250) — Новый SYSTEM_PROMPT «бот-абьюзер v2» + SUMMARY_ALIASES на прод (v2.25.0, НОВОЕ)
17. [Section 37: Epic 28](#37-epic-28--качество-памяти-векторы-репосты-алиасы-очистка-v2260) — Качество памяти: векторы, репосты, алиасы, очистка (v2.26.0, НОВОЕ)

---

## 1. Задача 1 — Баг `danger_word` + Forwarded Messages

### 1.1 Симптомы

- Бот детектит danger-слова в обычных текстовых сообщениях любых юзеров.
- Бот **абсолютно слеп** к тем же словам, если они находятся внутри репостов (forwarded messages из каналов или от других пользователей).
- Затрагивает как `common` сервис (danger), так и `slavik` сервис (war_alert).

### 1.2 Root Cause Analysis

Выявлены **два слоя** проблем:

#### Слой A (ПОДТВЕРЖДЁННЫЙ ROOT CAUSE): Propagation-блокировка в `dead_page_router`

**Файл:** `handlers/dead_page_trigger.py`

```python
@dead_page_router.message(F.forward_origin)        # ← матчит ЛЮБОЕ forwarded-сообщение
async def on_forward(message: types.Message):
    origin = message.forward_origin
    if not isinstance(origin, MessageOriginChannel):
        return                                        # ← implicit None → БЛОКИРУЕТ propagation!
    ...
    if not is_target:
        return                                        # ← implicit None → БЛОКИРУЕТ propagation!
```

**Механика бага:**
1. `dead_page_router` находится на позиции **4** в цепочке роутеров (см. Приложение A).
2. Фильтр `F.forward_origin` матчит **все** forwarded-сообщения — от любых пользователей и из любых каналов.
3. Внутри хэндлера `on_forward`: если это НЕ репост из `@d_pages`, хэндлер делает `return` (без `UNHANDLED`) — что в aiogram 3.x означает **«сообщение обработано»**.
4. `Router.propagate_event()` видит не-`UNHANDLED` результат → останавливает propagation.
5. Последующие роутеры — `war_alert_router` (4b) и `common_router` (4c) — **не получают событие вовсе**.

**Последствия:**
- Любое forwarded-сообщение НЕ из @d_pages **полностью игнорируется** всеми нижестоящими роутерами.
- `DangerWordFilter` (common_router, 4c) не видит forwarded-сообщений → danger не срабатывает.
- `WarWordFilter` (war_alert_router, 4b) не видит forwarded-сообщений → war_alert для Славы тоже не срабатывает на репостах.
- Обычные (не-forwarded) сообщения проходят нормально — `F.forward_origin` фильтр не матчит.

**Почему `otboy` («отбой») работает, а `danger` — нет?**
Это иллюзия. `otboy_handler` работает **только для обычных сообщений**, не для forwarded. Когда пользователь тестировал «отбой», он, вероятно, отправлял обычное (не-forwarded) сообщение, которое свободно проходило мимо `dead_page_router`. Но для forwarded-сообщений **оба хэндлера** (`otboy_handler` и `danger_handler`) одинаково невидимы.

#### Слой B (ПРОВЕРЕНО — НЕ баг): `.env` override словаря

Вопреки первоначальной гипотезе в старой версии ARCHITECTURE.md, `.env.example` содержит `DANGER_WORDS=` (пусто) — это **корректно**. Пустое значение означает «используй список из `filters/word_lists.py` (135+ слов)». Локальный `.env` также не содержит переопределения `DANGER_WORDS`.

**Тем не менее**, рекомендуется Builder'у проверить `.env` на сервере через SSH (см. Приложение B) — на случай, если переменная была добавлена вручную при предыдущих деплоях.

### 1.3 WAR_CHANNEL_IDS — архитектурная проверка

**Текущая архитектура (корректна):**

| Хэндлер | Роутер | Фильтры | Назначение |
|---------|--------|---------|-----------|
| `war_channel_repost_handler` | `war_alert_router` (4b) | `TargetChannelFilter(WAR_CHANNEL_IDS, WAR_CHANNEL_USERNAMES)` | Репост из конкретного war-канала → reply фразой (независимо от содержания) |
| `war_keyword_handler` | `war_alert_router` (4b) | `UserIdFilter(SLAVIK_USER_ID)` + `WarWordFilter()` | Сообщение Славы с danger-словом → reply фразой |
| `danger_handler` | `common_router` (4c) | `DangerWordFilter()` | Сообщение **любого** юзера с danger-словом → random медиа из `common/danger/` |

**Логика работы:**
- `WAR_CHANNEL_IDS` — **аддитивный** триггер: форсирует реакцию на репост из конкретных каналов, даже без danger-слов.
- `DangerWordFilter` в `common_router` — **независимый** триггер: ищет danger-слова в любых сообщениях (включая forwarded) для всех пользователей.
- Если `WAR_CHANNEL_IDS` пуст — `war_channel_repost_handler` просто никогда не срабатывает, а поиск danger-слов продолжает работать через `DangerWordFilter`.
- **Архитектура требованиям соответствует** — переделывать логику WAR_CHANNEL_IDS не требуется.

### 1.4 Устранение дублирования `WarWordFilter` ↔ `DangerWordFilter`

**Текущее состояние:**
- `filters/war_word.py::WarWordFilter` — дублирует логику `DangerWordFilter` (тот же список слов `DANGER_WORDS`, те же regex-паттерны)
- `filters/danger_word.py::DangerWordFilter` — более функциональный (возвращает `{"matched_word": ...}` для quoting)
- Оба используют ОДИН источник слов: `filters/word_lists.py::DANGER_WORDS`

**Архитектурное решение:** удалить `WarWordFilter` как отдельный класс, использовать `DangerWordFilter` во всех точках.

**План (для Builder):**
1. В `handlers/war_alert.py`: заменить импорт `from filters.war_word import WarWordFilter` на `from filters.danger_word import DangerWordFilter`
2. Заменить `WarWordFilter()` → `DangerWordFilter()` в декораторе `war_keyword_handler`
3. Удалить файл `filters/war_word.py`
4. Удалить связанные тесты для `WarWordFilter` или адаптировать их под `DangerWordFilter`

### 1.5 Исправление (конкретные изменения для Builder)

**Файл 1: `handlers/dead_page_trigger.py`**

Добавить импорт UNHANDLED и заменить `return` на `return UNHANDLED` в двух местах:

```python
# Добавить импорт (в начало файла):
from aiogram.dispatcher.event.bases import UNHANDLED

# Строка ~42 (не-channel forward origin):
if not isinstance(origin, MessageOriginChannel):
    logger.debug(f"Forward origin is not a channel: {type(origin).__name__}")
    return UNHANDLED          # ← было: return

# Строка ~56 (не-target channel):
if not is_target:
    return UNHANDLED          # ← было: return
```

**Файл 2: `handlers/war_alert.py`**

Заменить `WarWordFilter` → `DangerWordFilter`:

```python
# Было:
from filters.war_word import WarWordFilter
...
@war_alert_router.message(UserIdFilter(settings.SLAVIK_USER_ID), WarWordFilter())

# Стало:
from filters.danger_word import DangerWordFilter
...
@war_alert_router.message(UserIdFilter(settings.SLAVIK_USER_ID), DangerWordFilter())
```

**Файл 3: `filters/war_word.py`**

Удалить файл.

### 1.6 Проверка, что DangerWordFilter корректно видит forwarded-сообщения

После исправления propagation (1.5), `common_router` будет **получать** forwarded-сообщения. Остаётся вопрос: видит ли сам `DangerWordFilter` текст forwarded-сообщения?

**Проверка кода `DangerWordFilter.__call__`:**
```python
content = message.text or message.caption
```

**Анализ поведения aiogram/Telegram API для forwarded-сообщений:**

| Тип forwarded-сообщения | Где лежит текст | Видит ли фильтр? |
|------------------------|----------------|-----------------|
| Пересланный текст (без своего комментария) | `message.text` | ✅ Да |
| Пересланное медиа с подписью (caption) | `message.caption` | ✅ Да |
| Пересланное медиа БЕЗ подписи | `message.text` = None, `message.caption` = None | ❌ Нет (нечего матчить) |
| Пересланное сообщение + пользователь ДОБАВИЛ свой текст | `message.text` = свой текст, оригинал может быть потерян | ⚠️ Только свой текст юзера |

**Вывод:** фильтр `DangerWordFilter` (и `OtboyWordFilter`) корректно обрабатывает forwarded-сообщения **при условии**, что forwarded-сообщение содержит текст (в `message.text` или `message.caption`). Дополнительных изменений в фильтр **не требуется**.

Если требуется искать danger-слова **в теле оригинала** пересланного сообщения даже когда пользователь добавил свой текст поверх — это принципиально невозможно через Bot API, т.к. оригинальный текст не экспонируется отдельным полем при forwarded-with-added-text.

---

## 2. Задача 2 — Поломка репостинга `dead page`

### 2.1 Симптомы

- Бот корректно репостит старый пост ID=3 (фото + подпись).
- Новый пост не появляется в чате.
- Ранее проблема была с MediaGroup (3 фото + текст) — бот репостил по частям.
- Канал перешёл на Rich Message формат (Telegram Bot API 10.2, июль 2026) — одно сообщение с 3 фото + текст.
- Этот новый Rich-пост бот игнорирует.

### 2.2 Что такое Rich Message (Bot API 10.2)

**Подтверждено:** 14 июля 2026 Telegram выпустил Bot API 10.2 с поддержкой Rich Messages.
- `message.rich_message` — новое поле типа `RichMessage` (список блоков: paragraph, photo, table, и т.д.)
- Это НЕ `MediaGroup` (media_group_id отсутствует)
- Это технически ОДНО сообщение с ОДНИМ `message_id`
- `bot.forward_message()` должен работать для Rich Messages так же, как для любых других типов (forward by-reference)

**Установленная версия aiogram (3.29.1) подтверждённо содержит типы:**
```python
# aiogram/types/message.py
rich_message: RichMessage | None = None

# aiogram/types/rich_message.py
class RichMessage(TelegramObject):
    blocks: list[RichBlockUnion]
    is_rtl: bool | None = None
```

### 2.3 Что УЖЕ есть в коде

**Rich Message детекция реализована** в `services/dead_page_relay.py`:

```python
def _is_rich_message(sent) -> bool:
    """Return True if the forwarded message is a Rich Message (Bot API 10.2+)."""
    if _RichMessageType is None:
        return False
    return isinstance(getattr(sent, 'rich_message', None), _RichMessageType)
```

Используется в двух точках:
1. `_forward_single()` — строка 295: после `bot.forward_message()` проверяет `_is_rich_message(sent)` → если да, обновляет DB и возвращает `True`
2. `_forward_with_heuristic()` — строка 434: то же самое в эвристическом пути

**Трекер в `bot.py`** — `track_relay_post` логирует Rich Messages при индексации, но не сохраняет их в `relay_album_map` (правильно — у Rich Messages нет media_group_id, альбом не нужен).

### 2.4 Root Cause — почему новый пост не появляется

Механизм НЕ в отсутствии Rich Message-поддержки (она есть). Проблема в **алгоритме поиска новых ID**.

**Как работает поиск (`_try_forward_from_channel`):**

```
1. Если last_msg_id известен (>0):
   → Forward scan: последовательно пробуем ID last_msg_id+1 ... last_msg_id+20
   → Каждый ID: _forward_single() → если success → return True

2. Если forward scan не дал результата:
   → Строим search ranges (anchored + discovery)
   → Для каждого range:
     - Если range_size ≤ 50: sequential scan (перебор всех ID)
     - Иначе: random probing (до 5 попыток на range)

3. Если все ranges exhausted → return False → fallback на локальные медиа
```

**Сценарий, объясняющий симптом:**

A. **Холодный старт** (первый вызов, `last_msg_id = None`):
   - Forward scan **не запускается** (условие `if last_msg_id and last_msg_id > 0` не выполняется)
   - Используются `_DISCOVERY_RANGES`: `[(1,10), (1,50), (1,200), (1,500), (1,2000)]`
   - Range (1,10) — последовательный скан 10 ID → **находит ID=3** (старый пост) → forward success → `last_msg_id = 3`

B. **Следующий вызов** (`last_msg_id = 3`):
   - Forward scan: ID 4,5,6,7,...23
   - ID=7 должно быть найдено! `_forward_single(chat_id, 7, 3)` → `bot.forward_message()` → `_is_rich_message(sent)` → True → DB update → return True
   - **Теоретически должно работать.**

C. **Почему может не работать на практике:**
   1. **`_is_rich_message(sent)` возвращает False** — если aiogram 3.29.1 не десериализует `rich_message` из ответа `forwardMessage` API. В этом случае код падает в `_forward_album_post_send()` → Path 2 (single post) → обновляет DB → return True. **Сообщение ВСЁ РАВНО переслано** (forward_message уже вызван), но без Rich Message-логирования.
   2. **Forward scan никогда не вызывается повторно** — `send_dead_page` срабатывает только при репосте из @d_pages. Если после публикации Rich-поста никто не репостнул из @d_pages, бот просто не пытается искать новые посты.
   3. **Между вызовами прошёл cooldown-блок** — `DEAD_PAGE_COOLDOWN_SECONDS` (по умолчанию 0 — без блокировки). Не является причиной при дефолтных настройках.

**Наиболее вероятная причина (архитектурная):** бот **реактивен** — он ищет новые посты только когда получает репост из @d_pages. Если репост из @d_pages не происходит, сканирование канала не запускается. Старый пост ID=3 был найден при предыдущем репосте, а для поиска ID=7 новый репост мог не произойти.

**Вторая вероятная причина:** на проде мог сработать `DEAD_PAGE_COOLDOWN_SECONDS > 0`, из-за чего повторные вызовы `send_dead_page` блокируются.

### 2.5 Архитектурное решение (для Builder)

**Не требуется** писать Rich Message-парсер с нуля — форвард работает by-reference через Telegram API.

**Требуемые изменения:**

1. **Увеличить дальность forward scan:** заменить `_FORWARD_SCAN_LIMIT = 20` → `50` или `100`, чтобы покрыть больше новых ID за один вызов.

2. **Улучшить логирование Rich Message:**
   - В `_forward_single()`: после `bot.forward_message()` залогировать `sent.rich_message is not None` (INFO-level), даже если `_is_rich_message` возвращает False — для диагностики десериализации.
   - В `track_relay_post`: повысить уровень лога Rich Message с DEBUG до INFO.

3. **Добавить fallback: если `_is_rich_message` возвращает False, но сообщение успешно переслано:**
   ```python
   sent = await self.bot.forward_message(...)
   if _is_rich_message(sent):
       # Current path — OK
   else:
       # Check if original message WAS a Rich Message (heuristic):
       # If sent has no photo/caption but has text entities → might be Rich Message
       logger.info("Forwarded message: rich_message attribute absent, photo=%s, caption=%s",
                   sent.photo is not None, sent.caption is not None)
   ```

4. **Опционально: проактивное сканирование** — если архитектура позволяет, можно добавить фоновую задачу, которая периодически (раз в N минут) проверяет relay-канал на новые посты через forward scan. Но это изменение архитектуры, требующее отдельного согласования.

---

## 3. Задача 3 — Фича `mimic` (передразнивание)

### 3.1 Предоставленный алгоритм

Пользователь предоставил готовый, протестированный алгоритм трансформации текста:

```python
WORD_MAP = {
    r'\bчт?о\b': 'фе', r'\bч[еёо]\b': 'фе', r'\bчт?о-то\b': 'фе-то',
    r'\bч[еёо]-то\b': 'фе-то', r'\bкого\b': 'каво', r'\bникого\b': 'никаво',
    r'\bчего\b': 'фево', r'\bничего\b': 'нифево', r'\bпочему\b': 'патему',
    r'\bпотому\s+что\b': 'патаму фе', r'\bзачем\b': 'затем', r'\bкуда\b': 'кудя',
    r'\bоткуда\b': 'аткудя', r'\bкогда\b': 'када', r'\bтогда\b': 'тада',
    r'\bвсегда\b': 'сигда', r'\bс[еи]йчас\b': 'сяс', r'\bщ[ая]с\b': 'сяс',
    r'\bщ[ая]\b': 'ся', r'\bвообще\b': 'вафе', r'\bваще\b': 'вафе',
    r'\bвообще-?то\b': 'вафе-то', r'\bбольше\b': 'бофе', r'\bбольшие\b': 'бофые',
    r'\bконечно\b': 'канефна', r'\bпожалуйста\b': 'пазяста',
    r'\bздравствуйт?е?\b': 'длатути', r'\bхочу\b': 'хатю', 
}

SUBSTR_MAP = {
    r'шься\b': 'фся', r'шь\b': 'ф', r'т[ь]?ся\b': 'тца',
    r'сл': 'фл', r'дст': 'тст',
}

CONSONANT_MAP = {
    "р": "л", "Р": "Л", "ш": "ф", "Ш": "Ф", "щ": "ф", "Щ": "Ф",
    "ж": "з", "Ж": "З", "ч": "т", "Ч": "Т",
}

VOWEL_MAP_AFTER_CONSONANT = {"у": "ю", "У": "Ю"}
```

Алгоритм применяет трансформации послойно: WORD_MAP → SUBSTR_MAP → CONSONANT_MAP + VOWEL_MAP, с сохранением регистра (`_match_case`).

### 3.2 Текущая архитектура mimic в проекте

Mimic **уже интегрирован** в два сервиса:

```
services/mimic_transform.py   ← Трансформация (упрощённая версия, только consonant/vowel map)
services/mimic_relay.py       ← Cooldown + dispatch для common сервиса
handlers/common.py            ← mimic_handler (для MIMIC_VICTIM_USER_IDS)
handlers/slavik.py            ← slavik_catchall_handler (mimic для Славы)
```

**Конфигурация (уже существует):**
```
MIMIC_VICTIM_USER_IDS=138811255      # ID жертв (common)
MIMIC_MIN_WORDS=5                    # Мин. слов для активации (common)
MIMIC_COOLDOWN_SECONDS=60.0          # Кулдаун между ответами (common)
SLAVIK_MIMIC_MIN_WORDS=5             # Мин. слов для Славы
SLAVIK_MIMIC_COOLDOWN_SECONDS=60.0   # Кулдаун для Славы
```

### 3.3 Архитектурный план интеграции

**Единственное изменение:** заменить содержимое `services/mimic_transform.py` на предоставленный алгоритм.

**Что НЕ менять:**
- `services/mimic_relay.py` — не меняется (использует `mimic_transform()` как чистую функцию)
- `handlers/common.py::mimic_handler` — не меняется (использует `MimicRelay`)
- `handlers/slavik.py::slavik_catchall_handler` — не меняется (вызывает `mimic_transform()` напрямую)
- `config/settings.py` — не меняется (все нужные параметры уже есть)

**Контракт `mimic_transform()`:**
- Вход: `str` (текст сообщения)
- Выход: `str` (трансформированный текст)
- Чистая функция без сайд-эффектов
- Обрабатывает пустую строку (возвращает пустую)

**Файл для замены:** `services/mimic_transform.py`

Полный код, который должен быть в файле (предоставлен пользователем):

```python
import re

WORD_MAP = {
    r'\bчт?о\b': 'фе', r'\bч[еёо]\b': 'фе', r'\bчт?о-то\b': 'фе-то',
    r'\bч[еёо]-то\b': 'фе-то', r'\bкого\b': 'каво', r'\bникого\b': 'никаво',
    r'\bчего\b': 'фево', r'\bничего\b': 'нифево', r'\bпочему\b': 'патему',
    r'\bпотому\s+что\b': 'патаму фе', r'\bзачем\b': 'затем', r'\bкуда\b': 'кудя',
    r'\bоткуда\b': 'аткудя', r'\bкогда\b': 'када', r'\bтогда\b': 'тада',
    r'\bвсегда\b': 'сигда', r'\bс[еи]йчас\b': 'сяс', r'\bщ[ая]с\b': 'сяс',
    r'\bщ[ая]\b': 'ся', r'\bвообще\b': 'вафе', r'\bваще\b': 'вафе',
    r'\bвообще-?то\b': 'вафе-то', r'\bбольше\b': 'бофе', r'\bбольшие\b': 'бофые',
    r'\bконечно\b': 'канефна', r'\bпожалуйста\b': 'пазяста',
    r'\bздравствуйт?е?\b': 'длатути', r'\bхочу\b': 'хатю', 
}

SUBSTR_MAP = {
    r'шься\b': 'фся', r'шь\b': 'ф', r'т[ь]?ся\b': 'тца',
    r'сл': 'фл', r'дст': 'тст',
}

CONSONANT_MAP = {
    "р": "л", "Р": "Л", "ш": "ф", "Ш": "Ф", "щ": "ф", "Щ": "Ф",
    "ж": "з", "Ж": "З", "ч": "т", "Ч": "Т",
}

VOWEL_MAP_AFTER_CONSONANT = {"у": "ю", "У": "Ю"}
CYRILLIC_CONSONANTS = frozenset("бвгджзйклмнпрстфхцчшщБВГДЖЗЙКЛМНПРСТФХЦЧШЩ")

def _match_case(match: re.Match, new_word: str) -> str:
    word = match.group(0)
    if word.isupper(): return new_word.upper()
    if word.istitle(): return new_word.capitalize()
    return new_word.lower()

def mimic_transform(text: str) -> str:
    if not text: return text
    for pattern, replacement in WORD_MAP.items():
        text = re.sub(pattern, lambda m, r=replacement: _match_case(m, r), text, flags=re.IGNORECASE)
    for pattern, replacement in SUBSTR_MAP.items():
        text = re.sub(pattern, lambda m, r=replacement: _match_case(m, r), text, flags=re.IGNORECASE)
    chars = list(text)
    result = []
    for i, ch in enumerate(chars):
        if ch in CONSONANT_MAP:
            result.append(CONSONANT_MAP[ch])
        elif ch in VOWEL_MAP_AFTER_CONSONANT and i > 0 and text[i - 1] in CYRILLIC_CONSONANTS:
            result.append(VOWEL_MAP_AFTER_CONSONANT[ch])
        else:
            result.append(ch)
    return "".join(result)

def count_words(text: str) -> int:
    """Count words in text for mimic threshold check."""
    if not text: return 0
    return len(text.split())
```

**Важно:** функция `count_words()` сохранена, т.к. используется в `MimicRelay.should_trigger()` и `slavik_catchall_handler`.

### 3.4 Точки интеграции (без изменений)

```
                    ┌─────────────────────────┐
                    │  mimic_transform(text)  │
                    │  (services/mimic_       │
                    │   transform.py)         │
                    └──────┬────────┬─────────┘
                           │        │
              ┌────────────┘        └────────────┐
              ▼                                  ▼
    ┌──────────────────┐              ┌──────────────────┐
    │  MimicRelay      │              │  slavik_catchall │
    │  (common service) │              │  _handler        │
    │                  │              │  (slavik router) │
    │  used by:        │              │                  │
    │  mimic_handler   │              │  direct call to  │
    │  (common_router) │              │  mimic_transform │
    └──────────────────┘              └──────────────────┘
```

---

## 4. Задача 4 — Смена путей slavik media + рандомный медиа-пикер

### 4.1 Текущее состояние

**Файловая структура `media/slavik/`:**
```
media/slavik/
├── slavic_chlen.mp4           ← F3 GIF interval (каждые N сообщений)
└── slavik_random/
    ├── slavic_na_litso.jpg    ← F8 Photo interval (каждый N-й "пошёл нахуй")
    └── slavic_did_you_dream.jpg
```

**Текущие env-переменные:**
```
GIF_PATH=media/slavic_chlen.mp4               # F3
SLAVIC_PHOTO_PATH=media/slavic_na_litso.jpg   # F8 (один файл)
SLAVIC_PHOTO_INTERVAL=10                      # Каждые N ответов
```

**Текущая логика F8 в `slavik_catchall_handler`:**
```python
if should_send_photo:
    await message.answer_photo(photo=FSInputFile(settings.SLAVIC_PHOTO_PATH))
```

### 4.2 Требования

1. `slavic_chlen.mp4` — **уже** лежит в `media\slavik\` → путь в `GIF_PATH` менять не нужно.
2. `slavic_na_litso.jpg` — **уже** лежит в `media\slavik\slavik_random\` → нужно обновить логику.
3. Вместо одного жёстко заданного файла — **рандомный** выбор из всей директории `slavik_random/`.
4. Поддержка всех типов: photo (.jpg/.png/...), video (.mp4/.mov/...), animation (.mp4 с "gif" в имени).

### 4.3 Архитектурное решение

**Новая env-переменная:**
```
SLAVIC_RANDOM_DIR=media/slavik/slavik_random
```

**Старая переменная `SLAVIC_PHOTO_PATH`** — депрекейтится, но сохраняется в `settings.py` для обратной совместимости (можно использовать как fallback, если `SLAVIC_RANDOM_DIR` пуст или не существует).

**Изменения в `handlers/slavik.py`** (только ветка Photo Interval):

```python
# Было (псевдокод):
if should_send_photo:
    filepath = settings.SLAVIC_PHOTO_PATH
    if not Path(filepath).exists():
        logger.warning("file not found: %s", filepath)
    else:
        await message.answer_photo(photo=FSInputFile(filepath))

# Стало (псевдокод):
if should_send_photo:
    media_dir = Path(settings.SLAVIC_RANDOM_DIR)
    if media_dir.exists():
        files = [f for f in media_dir.iterdir() if f.is_file()]
        if files:
            picked = random.choice(files)
            media_type = _detect_slavik_media_type(picked)  # photo/video/animation
            await _send_slavik_media(message, picked, media_type)
            return
    # Fallback: старый SLAVIC_PHOTO_PATH
    ...
```

**Функция детекции типа медиа:**
Использовать ту же логику, что и в `CommonRelay._detect_media_type()`:
- `.jpg/.jpeg/.png/.webp/.bmp` → `photo`
- `.mp4/.mov/.webm` с "gif" в имени → `animation`
- `.mp4/.mov/.webm` без "gif" → `video`

**Рекомендация:** вынести `_detect_media_type` в общий утилитный модуль (например, `services/media_utils.py`), чтобы `CommonRelay` и slavik handler использовали один и тот же код. ИЛИ продублировать функцию в `handlers/slavik.py` (проще, но дублирование).

**Решение архитектора:** дублировать функцию в `handlers/slavik.py` как приватную `_detect_slavik_media_type()`. Вынос в общий утилитный модуль — за рамками данной задачи, может быть сделан в будущем рефакторинге.

### 4.4 Файлы для изменения

| Файл | Что меняется |
|------|-------------|
| `config/settings.py` | Добавить `SLAVIC_RANDOM_DIR`, пометить `SLAVIC_PHOTO_PATH` как deprecated |
| `.env.example` | Добавить `SLAVIC_RANDOM_DIR`, закомментировать старый `SLAVIC_PHOTO_PATH` |
| `handlers/slavik.py` | Переписать фото-ветку в `slavik_catchall_handler` |
| Тесты | Обновить тесты для `slavik_catchall_handler` |

### 4.5 Важно: НЕ трогать F3 GIF

`GIF_PATH=media/slavic_chlen.mp4` — это **отдельная** фича (счётчик сообщений через `MessageCounterMiddleware`). Она не меняется. Файл `slavic_chlen.mp4` уже лежит в `media/slavik/` — путь корректен.

---

## 5. Сводный план для Builder

### 5.1 Порядок реализации

| # | Задача | Файлы | Приоритет | Оценка сложности |
|---|--------|-------|-----------|-----------------|
| 1 | **Задача 1 — Propagation fix** | `handlers/dead_page_trigger.py` | 🔴 Критический | Низкая (2 строки + импорт) |
| 2 | **Задача 1 — Удаление WarWordFilter** | `handlers/war_alert.py`, удалить `filters/war_word.py` | 🟡 Средний | Низкая (замена импорта) |
| 3 | **Задача 2 — Улучшение forward scan** | `services/dead_page_relay.py` | 🟡 Средний | Низкая (изменить константу + логи) |
| 4 | **Задача 3 — Mimic алгоритм** | `services/mimic_transform.py` | 🟢 Обычный | Низкая (замена файла) |
| 5 | **Задача 4 — Slavik random media** | `handlers/slavik.py`, `config/settings.py`, `.env.example` | 🟢 Обычный | Средняя (новая логика) |

### 5.2 Риски

| Риск | Вероятность | Влияние | Митигация |
|------|-----------|---------|-----------|
| `UNHANDLED` в dead_page_router ломает существующий flow для @d_pages репостов | Низкая | Высокое | Проверить, что `return UNHANDLED` только для non-target путей; target-путь делает `await _relay.send_dead_page()` и возвращает `None` (корректно) |
| Удаление `WarWordFilter` ломает war_alert | Низкая | Высокое | `DangerWordFilter` идентичен по поведению (тот же список слов, те же паттерны) |
| Rich Message не десериализуется в aiogram 3.29.1 | Средняя | Среднее | Диагностический лог INFO-level покажет `sent.rich_message is None`; forward при этом всё равно работает |
| Новый mimic алгоритм ломает существующие тесты | Высокая | Среднее | Полный прогон pytest до и после, обновление ожидаемых значений в тестах |

### 5.3 Тест-план

**Перед любыми изменениями:**
- `pytest` — полный suite, зафиксировать baseline

**После Задачи 1:**
- Тест: forwarded message с danger-словом → danger_handler вызывается
- Тест: forwarded message НЕ из @d_pages → common_router получает событие
- Тест: forwarded message ИЗ @d_pages → dead_page_router обрабатывает, propagation продолжается (для non-target логики)

**После Задачи 2:**
- Тест: Rich Message в relay-канале → форвардится (мок)
- Тест: forward scan находит ID за пределами старого 20-ID окна

**После Задачи 3:**
- Тест: `mimic_transform("что")` → `"фе"` и другие кейсы из WORD_MAP
- Тест: `mimic_transform("здравствуйте")` → `"длатути"`
- Тест: регрессия — все существующие mimic-тесты проходят

**После Задачи 4:**
- Тест: random media из `slavik_random/` — выбирается файл и определяется тип
- Тест: photo → `send_photo`, video → `send_video`, animation → `send_animation`
- Тест: пустая директория → fallback на старый `SLAVIC_PHOTO_PATH`

---

## Приложение A: Текущий Router Order

```
Position 0:  admin_commands_router     (/deadpage, /alangreet)
Position 1:  slava_presence_router     (ChatMemberUpdated: Slava join/leave)
Position 1b: alan_greeting_router      (ChatMemberUpdated: Alan join → greeting)
Position 2:  kostik_router             (UserIdFilter: Kostik → probability reply)
Position 3:  alan_router               (UserIdFilter: Alan → reply engine)
Position 4:  dead_page_router          (F.forward_origin: @d_pages reposts)  ← БЛОКИРУЕТ forwarded
Position 4b: war_alert_router          (WarWordFilter + TargetChannelFilter)
Position 4c: common_router             (OtboyWordFilter + DangerWordFilter + mimic)
Position 5:  slavik_router             (UserIdFilter: Slava → kucha + catchall)
Position 6:  vasya_router              (Text filters, no user restriction)
```

**Критическое наблюдение:** `dead_page_router` (4) использует `F.forward_origin` без ограничения по каналу. Фильтр матчит ЛЮБОЕ forwarded-сообщение, а handler возвращает `None` для non-target → propagation останавливается ДО `war_alert_router` (4b) и `common_router` (4c).

---

## Приложение B: Диагностическая SSH-проверка (для Задачи 1)

Builder должен выполнить эти проверки на сервере `nik@198.46.175.136:/var/www/admin_bot` **до внесения изменений**:

```bash
# 1. Проверить DANGER_WORDS в .env на сервере
cat .env | grep DANGER_WORDS
# Ожидается: DANGER_WORDS= (пусто) или отсутствие строки

# 2. Проверить статус процесса бота
systemctl status adminbot   # или какое имя у сервиса
# Сравнить "Active since" с временем последнего git pull

# 3. Проверить HEAD коммита на сервере
git log -1 --oneline
# Должен быть af93acb или новее

# 4. Проверить директорию media/common/danger/
ls -la media/common/danger/
# Должны быть danger_01.mp4, danger_02_gif.mp4, danger_boom.mp4
```

---

## 6. Epic 18 — Danger Service Fixes (три микро-бага)

> **Дата:** 2026-08-02
> **Статус:** Архитектурный анализ. Реализация НЕ начата.
> **Затрагиваемые файлы:** `services/common_relay.py`, `config/settings.py`, `bot.py`, `.env.example`, `tests/test_common.py`

---

### 6.1 Bug A — File scanning/selection robustness (недостаточное логирование + per-entry error handling)

#### 6.1.1 Симптом

Пользователь сообщает: «в danger было 3 файла, отправились только 2, третий ни разу не попался». Сейчас в danger 14 файлов.

#### 6.1.2 Root Cause Analysis

**Проверка текущего кода** (`services/common_relay.py`):

```python
# _scan_directory (строка 104-124):
for entry in base.iterdir():      # ← итерирует ВСЕ entry в директории
    if not entry.is_file():        # ← отсеивает поддиректории
        continue
    media_type = self._detect_media_type(entry)
    if media_type is not None:
        files.append((entry, media_type))

# send_common (строка 231):
filepath, media_type = random.choice(files)  # ← равновероятный выбор
```

**Заключение: логика СБОРА файлов корректна** — `iterdir()` итерирует все entry, `random.choice()` выбирает равномерно. Никаких хардкод-лимитов нет.

**НО выявлены два реальных дефекта:**

| Дефект | Расположение | Описание |
|--------|-------------|----------|
| **D1** | `_scan_directory` строка 110 | `entry.is_file()` может выбросить `OSError` для отдельных файлов (битый symlink, permission denied на одном файле). Это крашит ВЕСЬ `_scan_directory`, исключение прокидывается в `send_common` и глушится catch-all на строках 228-233 — **весь subdir пропускается молча.** |
| **D2** | `_scan_directory` строка 122-124 | После успешного сканирования в лог попадает только WARNING «no files» (если пусто). НЕТ info-лога с перечнем найденных файлов → невозможно диагностировать проблему «3-го файла» без захода на сервер. |

**Гипотеза про 3-й файл:** третий файл мог иметь неподдерживаемое расширение (например, `.mkv`, `.gif`), быть битым symlink-ом (OSError при `is_file()`), или быть добавленным позже. Без дополнительного логирования это невосстановимо.

#### 6.1.3 Исправление

**Файл: `services/common_relay.py` — метод `_scan_directory`**

Два изменения:

**(a) Per-entry OSError handling** — обернуть `entry.is_file()` и `_detect_media_type()` в try/except:

```python
# БЫЛО (строка 108-117):
for entry in base.iterdir():
    if not entry.is_file():
        continue
    media_type = self._detect_media_type(entry)
    if media_type is not None:
        files.append((entry, media_type))
    else:
        logger.debug(
            "CommonRelay: skipping unsupported file %s in %s",
            entry.name,
            subdir,
        )

# СТАЛО:
for entry in base.iterdir():
    try:
        if not entry.is_file():
            continue
        media_type = self._detect_media_type(entry)
        if media_type is not None:
            files.append((entry, media_type))
        else:
            logger.debug(
                "CommonRelay: skipping unsupported file %s in %s",
                entry.name,
                subdir,
            )
    except OSError:
        logger.warning(
            "CommonRelay: cannot access entry %s in %s — skipping",
            entry,
            subdir,
        )
        continue
```

**(b) INFO-лог после сканирования** — добавить после цикла:

```python
# После цикла for, перед проверкой `if not files:`:
logger.info(
    "CommonRelay: scanned %s — found %d supported files: %s",
    base,
    len(files),
    [(f.name, mt) for f, mt in files],
)
```

#### 6.1.4 Проверка random.choice unbiased

- `random.choice(files)` использует `random.Random.choice` → равномерное распределение по всей длине списка.
- Никаких фильтров, сортировок или лимитов перед выбором нет.
- **Баг не подтверждён** — `random.choice` работает корректно. Вероятность невыбора конкретного файла из 3 за N попыток = (2/3)^N. За 10 попыток ~1.7% — маловероятно, но возможно.

---

### 6.2 Bug B — GIF detection in filename (проверка по `stem` → проверка по `name`)

#### 6.2.1 Симптом

Пользователь: `danger_02_gif.mp4` был отправлен как video, а не animation.

#### 6.2.2 Root Cause Analysis

**Текущий код** (`services/common_relay.py` строка 76-78):

```python
if "gif" in filepath.stem.lower():
    return MEDIA_ANIMATION
```

**Тестирование на всех известных именах:**

| Имя файла | `Path.stem` | `"gif" in stem` | Результат |
|-----------|-------------|-----------------|-----------|
| `danger_02_gif.mp4` | `danger_02_gif` | ✅ True | animation ✓ |
| `danger_zelelyot_gif_02.mp4` | `danger_zelelyot_gif_02` | ✅ True | animation ✓ |
| `danger_nahryuck_gif.mp4` | `danger_nahryuck_gif` | ✅ True | animation ✓ |
| `danger_boom.mp4` | `danger_boom` | ❌ False | video ✓ |

**Вывод:** для ВСЕХ текущих файлов `stem`-проверка работает корректно. Баг `danger_02_gif.mp4` отправлен как video вероятно был в **старой версии**, где gif-проверка отсутствовала или имела другой вид.

**НО есть краевой случай:**

| Имя файла | `Path.stem` | `"gif" in stem` | Должно быть |
|-----------|-------------|-----------------|-------------|
| `file.gift.mp4` | `file.gift` | ✅ True (ошибка!) | video (gift ≠ gif) |

Это ложное срабатывание маловероятно (никто не называет файлы `.gift`), но архитектурно нечисто.

#### 6.2.3 Исправление

**Файл: `services/common_relay.py` — метод `_detect_media_type`**

Заменить `filepath.stem.lower()` на `filepath.name.lower()` + добавить проверку на word-boundary `_gif`:

```python
# БЫЛО (строка 76-78):
if "gif" in filepath.stem.lower():
    return MEDIA_ANIMATION

# СТАЛО:
# Check the full filename for 'gif' marker (more robust than stem-only).
# Also check for '_gif' pattern to avoid false positives like 'gift'.
fname = filepath.name.lower()
if "_gif" in fname or fname.startswith("gif") or ".gif" in fname:
    return MEDIA_ANIMATION
```

**Обоснование:**
- `filepath.name` вместо `filepath.stem` — покрывает multi-dot имена (редко, но безопаснее)
- `"_gif"` + `startswith("gif")` + `".gif"` — точный матчинг gif как токена
- `".gif"` покрывает случай `file.gif.mp4` (gif в середине имени)
- Ложно-положительные срабатывания исключены (`.gift` не матчится ни одним из правил)

---

### 6.3 Bug C — Separate danger cooldown (двойная блокировка)

#### 6.3.1 Требование

- Сохранить общий `COMMON_COOLDOWN_SECONDS` — блокирует otboy + danger вместе
- Добавить `DANGER_COOLDOWN_SECONDS` — дополнительно ограничивает ТОЛЬКО danger
- Otboy НЕ должен ограничиваться danger-кулдауном

**Матрица блокировок:**

| Сервис | Shared cooldown | Danger cooldown |
|--------|----------------|-----------------|
| otboy  | ✅ Проверяется | ❌ Не проверяется |
| danger | ✅ Проверяется | ✅ Проверяется |

**Пример (shared=30s, danger=60s):**

```
t=0s:  danger fires   → updates shared_ts[chat]=0, danger_ts[chat]=0
t=10s: otboy triggers → shared elapsed=10s < 30s → BLOCKED
t=40s: otboy triggers → shared elapsed=40s ≥ 30s → SENDS, shared_ts[chat]=40
t=45s: danger triggers → danger elapsed=45s < 60s → BLOCKED (danger cooldown)
                         shared elapsed=5s < 30s → also BLOCKED (shared)
t=70s: danger triggers → danger elapsed=70s ≥ 60s AND shared elapsed=30s ≥ 30s → SENDS
```

#### 6.3.2 Изменения

**Файл 1: `config/settings.py`**

Добавить новое поле после `COMMON_COOLDOWN_SECONDS`:

```python
# ── Common Service (Epic 15) ──
# Cooldown between media sends in the same chat (shared across otboy + danger).
# 0 = no cooldown (every trigger sends media).
COMMON_COOLDOWN_SECONDS: float = _env_float("COMMON_COOLDOWN_SECONDS", 0)

# Danger-specific cooldown (Epic 18). Additional restriction on top of shared.
# Danger sends are blocked if EITHER shared OR danger cooldown is active.
# 0 = no additional danger restriction.
DANGER_COOLDOWN_SECONDS: float = _env_float("DANGER_COOLDOWN_SECONDS", 60.0)
```

**Файл 2: `services/common_relay.py` — класс `CommonRelay`**

**(a) `__init__` — добавить параметр `danger_cooldown_seconds`:**

```python
# БЫЛО:
def __init__(
    self,
    bot: Bot,
    cooldown_seconds: float,
    media_base: str | None = None,
) -> None:
    self._bot = bot
    self._cooldown_seconds = cooldown_seconds
    self._media_base = media_base or settings.COMMON_MEDIA_BASE
    self._cooldowns: dict[int, float] = {}

# СТАЛО:
def __init__(
    self,
    bot: Bot,
    cooldown_seconds: float,
    danger_cooldown_seconds: float = 0,
    media_base: str | None = None,
) -> None:
    self._bot = bot
    self._cooldown_seconds = cooldown_seconds
    self._danger_cooldown_seconds = danger_cooldown_seconds
    self._media_base = media_base or settings.COMMON_MEDIA_BASE
    self._cooldowns: dict[int, float] = {}
    self._danger_cooldowns: dict[int, float] = {}
```

**(b) `send_common` — добавить danger-проверку перед shared-проверкой:**

```python
# БЫЛО (строка 223-230):
now = time.monotonic()

if self._cooldown_seconds > 0:
    last_sent = self._cooldowns.get(chat_id)
    if last_sent is not None:
        elapsed = now - last_sent
        if elapsed < self._cooldown_seconds:
            logger.info(...)
            return

# СТАЛО:
now = time.monotonic()

# Layer 1: danger-specific cooldown (only for danger sub-service)
if subdir == "danger" and self._danger_cooldown_seconds > 0:
    last_danger = self._danger_cooldowns.get(chat_id)
    if last_danger is not None:
        elapsed = now - last_danger
        if elapsed < self._danger_cooldown_seconds:
            logger.info(
                "CommonRelay: danger_cooldown_active | chat_id=%s | "
                "elapsed=%.1fs | remaining=%.1fs",
                chat_id,
                elapsed,
                self._danger_cooldown_seconds - elapsed,
            )
            return

# Layer 2: shared cooldown (blocks all sub-services)
if self._cooldown_seconds > 0:
    last_sent = self._cooldowns.get(chat_id)
    if last_sent is not None:
        elapsed = now - last_sent
        if elapsed < self._cooldown_seconds:
            logger.info(
                "CommonRelay: cooldown_active | chat_id=%s | subdir=%s | "
                "elapsed=%.1fs | remaining=%.1fs",
                chat_id,
                subdir,
                elapsed,
                self._cooldown_seconds - elapsed,
            )
            return
```

**(c) `send_common` — обновление кулдаунов после успешной отправки:**

```python
# БЫЛО (строка 243):
            self._cooldowns[chat_id] = now

# СТАЛО:
            self._cooldowns[chat_id] = now
            if subdir == "danger":
                self._danger_cooldowns[chat_id] = now
```

**Файл 3: `bot.py` — строка 78 (инициализация CommonRelay)**

```python
# БЫЛО:
common_relay = CommonRelay(bot, settings.COMMON_COOLDOWN_SECONDS)

# СТАЛО:
common_relay = CommonRelay(
    bot,
    cooldown_seconds=settings.COMMON_COOLDOWN_SECONDS,
    danger_cooldown_seconds=settings.DANGER_COOLDOWN_SECONDS,
)
```

**Файл 4: `.env.example`**

Добавить после `COMMON_COOLDOWN_SECONDS`:

```env
# Danger-specific cooldown in seconds (additional to shared).
# Danger sends are blocked if EITHER shared OR danger cooldown is active.
# 0 = no additional danger restriction (default: 60.0 = 1 minute).
DANGER_COOLDOWN_SECONDS=60.0
```

---

### 6.4 Сводка файлов и изменений для Builder

| # | Файл | Что меняется | Сложность |
|---|------|-------------|-----------|
| **A1** | `services/common_relay.py` `_scan_directory` (строка 104-124) | Per-entry OSError try/except + INFO-лог со списком найденных файлов | Низкая |
| **A2** | `services/common_relay.py` `send_common` (строка 228-233) | Проверить, что catch-all `(PermissionError, OSError)` больше не нужен (теперь per-entry) — оставить для `base.iterdir()` fail | Низкая |
| **B** | `services/common_relay.py` `_detect_media_type` (строка 76-78) | `filepath.stem.lower()` → `filepath.name.lower()` + word-boundary проверка `_gif` / `gif`-prefix / `.gif` | Низкая |
| **C1** | `config/settings.py` (после строки 96) | Добавить `DANGER_COOLDOWN_SECONDS: float = _env_float("DANGER_COOLDOWN_SECONDS", 60.0)` | Низкая |
| **C2** | `services/common_relay.py` `__init__` (строка 54-68) | Добавить параметр `danger_cooldown_seconds` + `_danger_cooldowns` dict | Низкая |
| **C3** | `services/common_relay.py` `send_common` (строка 210-250) | Layer-1 danger cooldown + Layer-2 shared cooldown + обновление обоих | Средняя |
| **C4** | `bot.py` (строка 78) | Передать `danger_cooldown_seconds=settings.DANGER_COOLDOWN_SECONDS` в `CommonRelay(...)` | Низкая |
| **C5** | `.env.example` (после COMMON_COOLDOWN_SECONDS) | Добавить `DANGER_COOLDOWN_SECONDS=60.0` | Низкая |
| **T** | `tests/test_common.py` | Новые тесты (см. §6.5) | Средняя |

---

### 6.5 Тест-план (Epic 18)

#### 6.5.1 Bug A — Scan directory

| ID | Тест | Ожидаемый результат |
|----|------|--------------------|
| T-A1 | `_scan_directory` с 3 .mp4 файлами | Возвращает 3 tuple, INFO-лог содержит имена всех 3 |
| T-A2 | `_scan_directory` с 1 битым файлом (OSError на `is_file()`) + 2 нормальными | Возвращает 2 tuple, WARNING лог про пропущенный файл |
| T-A3 | `send_common` → random.choice из 3 файлов (много вызовов) | Каждый файл выбран хотя бы раз за ~50 вызовов |

#### 6.5.2 Bug B — GIF detection

| ID | Тест | Ожидаемый результат |
|----|------|--------------------|
| T-B1 | `_detect_media_type(Path("danger_02_gif.mp4"))` | `MEDIA_ANIMATION` |
| T-B2 | `_detect_media_type(Path("danger_zelelyot_gif_02.mp4"))` | `MEDIA_ANIMATION` |
| T-B3 | `_detect_media_type(Path("danger_nahryuck_gif.mp4"))` | `MEDIA_ANIMATION` |
| T-B4 | `_detect_media_type(Path("gif_animation.mp4"))` (gif в начале имени) | `MEDIA_ANIMATION` |
| T-B5 | `_detect_media_type(Path("file.gift.mp4"))` (gift ≠ gif) | `MEDIA_VIDEO` (НЕ animation) |
| T-B6 | `_detect_media_type(Path("danger_boom.mp4"))` (без gif) | `MEDIA_VIDEO` |

#### 6.5.3 Bug C — Dual cooldown

| ID | Тест | Ожидаемый результат |
|----|------|--------------------|
| T-C1 | danger → otboy через 30s при shared=60s, danger=60s | otboy BLOCKED (shared ещё активен) |
| T-C2 | danger → danger через 30s при shared=60s, danger=60s | danger BLOCKED (оба кулдауна активны) |
| T-C3 | danger → danger через 70s при shared=60s, danger=60s | danger SENDS (оба истекли) |
| T-C4 | danger → otboy через 70s при shared=60s, danger=60s | otboy SENDS (shared истёк, danger не проверяется) |
| T-C5 | otboy → danger через 30s при shared=60s, danger=60s | danger BLOCKED (shared активен) |
| T-C6 | danger → danger через 30s при shared=0, danger=60s | danger BLOCKED (только danger кулдаун) |
| T-C7 | danger → otboy через 30s при shared=0, danger=60s | otboy SENDS (shared=0, danger не проверяется) |
| T-C8 | danger → danger через 30s при shared=60s, danger=0 | danger BLOCKED (shared кулдаун — danger отключен, но shared ещё активен) |

**Уточнение T-C8:** danger → danger через 30s при shared=60s, danger=0. Danger cooldown отключен, но shared ещё активен (60s). Ответ: BLOCKED (shared кулдаун).

**Уточнение T-C6:** danger → danger через 30s при shared=0, danger=60s. Shared отключен, danger кулдаун активен. Ответ: BLOCKED (danger кулдаун).

#### 6.5.4 Существующие тесты — проверка регрессии

Все существующие тесты в `TestCommonRelayCooldown` должны проходить без изменений, т.к. `danger_cooldown_seconds` по умолчанию = 0 (если не передано явно) — а существующие тесты создают `CommonRelay(bot, cooldown_seconds=X)` без danger-параметра.

**НО:** сигнатура `__init__` меняется (добавляется необязательный параметр), поэтому:
- Существующие вызовы `CommonRelay(mock_bot, cooldown_seconds=X)` остаются валидными.
- Но `danger_cooldown_seconds` по умолчанию = 60.0 для проду, а для тестов нужно = 0.
- **Решение:** в тестовых fixture явно передавать `danger_cooldown_seconds=0` ИЛИ установить дефолт 0 в `__init__`, а 60.0 передавать из `bot.py`.

**Архитектурное решение (финальное):**
- Дефолт в `__init__`: `danger_cooldown_seconds: float = 0` (безопасно для тестов)
- В `bot.py`: явно передать `danger_cooldown_seconds=settings.DANGER_COOLDOWN_SECONDS` (60.0 на проде)
- Это идиоматично: код модуля не завязывается на settings, конфигурация инжектится извне

---

### 6.6 Риски (Epic 18)

| Риск | Вероятность | Влияние | Митигация |
|------|-----------|---------|-----------|
| Per-entry OSError ловит и глушит ошибки, маскируя проблемы с файловой системой | Низкая | Среднее | WARNING-лог с именем проблемного entry — ошибка не теряется |
| `_gif`-проверка слишком строгая и НЕ матчит существующие имена (например, `somegif.mp4` без подчёркивания) | Низкая | Высокое | Текущие имена ВСЕ содержат `_gif`; дополнительно проверяется `startswith("gif")` |
| Двойной кулдаун слишком агрессивен, danger практически никогда не срабатывает | Средняя | Среднее | Дефолт 60s = 1 минута — разумно; админ может выставить 0 для отключения |
| Тесты падают из-за изменения сигнатуры `__init__` | Низкая | Низкое | Дефолт `danger_cooldown_seconds=0` сохраняет обратную совместимость |

---

@Orchestrator Epic 18 architecture ready, passing the baton.

@Orchestrator Architecture is ready, passing the baton.

---

## 7. Epic 19 — Сервис Olya (Video Trigger → Random Media)

> **Дата:** 2026-08-02
> **Статус:** Архитектурный дизайн. Реализация НЕ начата.
> **Затрагиваемые файлы:** `filters/olya_video.py` (новый), `services/olya_relay.py` (новый), `handlers/olya.py` (новый), `config/settings.py`, `bot.py`, `tests/test_olya.py` (новый)

---

### 7.1 Overview and Purpose

Olya — сервис, реагирующий на видеосообщения от конкретного пользователя (@ole4444444ka, ID 834424825). При получении видео-сообщения бот отправляет случайный медиа-файл из директории `media/olya/cringe/` **без reply/quote** — простым сообщением через `bot.send_*`.

**Конфигурация триггера (все опции независимо настраиваются):**

| Условие | Переменная | По умолчанию |
|---------|-----------|-------------|
| Видео с текстом "Спасибо, что пользуетесь - @SaveAsBot'ом" в caption | `OLYA_CAPTION_ENABLED=True` | True |
| Репост из канала @SaveAsBot (channel ID 523131145) | `OLYA_REPOST_ENABLED=True` | True |
| Всегда отправлять (Condition B — просто от этого пользователя с видео) | `OLYA_ALWAYS_SEND=True` | True |

**Критическое отличие от CommonRelay:** медиа отправляется **plain-сообщением** — без `ReplyParameters`, без цитирования слова. Это просто `bot.send_video(chat_id, video=FSInputFile(path))`. Сообщение-триггер не цитируется.

---

### 7.2 Architecture Diagram (text-based)

```
┌──────────────────────────────────────────────────────────────────────┐
│                        EPIC 19: Olya Service                        │
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  User @ole4444444ka (ID: 834424825)                                  │
│       │                                                              │
│       │  video message / forwarded video                             │
│       ▼                                                              │
│  ┌─────────────────────────────────────────┐                         │
│  │  FILTER LAYER                           │                         │
│  │  filters/olya_video.py                  │                         │
│  │                                         │                         │
│  │  OlyaVideoFilter(BaseFilter)            │                         │
│  │  ┌───────────────────────────────────┐  │                         │
│  │  │ 1. from_user.id == 834424825?    │  │                         │
│  │  │ 2. media type matches config?    │  │                         │
│  │  │ 3. caption text detection?       │  │                         │
│  │  │ 4. SaveAsBot repost detection?   │  │                         │
│  │  │ 5. OLYA_ALWAYS_SEND fallback?    │  │                         │
│  │  └──────────────┬───────────────────┘  │                         │
│  └─────────────────┼──────────────────────┘                         │
│                    │ returns dict or False                           │
│                    ▼                                                 │
│  ┌─────────────────────────────────────────┐                         │
│  │  SERVICE LAYER                          │                         │
│  │  services/olya_relay.py                 │                         │
│  │                                         │                         │
│  │  OlyaRelay                              │                         │
│  │  ┌───────────────────────────────────┐  │                         │
│  │  │ _scan_directory()                 │  │                         │
│  │  │ _detect_media_type()              │  │                         │
│  │  │ send_olya(chat_id)                │  │                         │
│  │  │   ├─ cooldown check (monotonic)  │  │                         │
│  │  │   ├─ random.choice(files)        │  │                         │
│  │  │   └─ _send_file(chat_id, ...)    │  │                         │
│  │  │       └─ NO ReplyParameters!     │  │                         │
│  │  └───────────────────────────────────┘  │                         │
│  └─────────────────┬──────────────────────┘                         │
│                    │                                                 │
│                    ▼                                                 │
│  ┌─────────────────────────────────────────┐                         │
│  │  HANDLER LAYER                          │                         │
│  │  handlers/olya.py                       │                         │
│  │                                         │                         │
│  │  olya_router (name="olya")              │                         │
│  │  ┌───────────────────────────────────┐  │                         │
│  │  │ olya_handler(message)             │  │                         │
│  │  │   ├─ _service.send_olya(chat_id)  │  │                         │
│  │  │   ├─ catch Exception              │  │                         │
│  │  │   └─ return UNHANDLED             │  │                         │
│  │  └───────────────────────────────────┘  │                         │
│  └─────────────────────────────────────────┘                         │
│                    │                                                 │
│                    ▼  UNHANDLED (propagation continues)              │
│  ┌─────────────────────────────────────────┐                         │
│  │  Next routers in chain...               │                         │
│  └─────────────────────────────────────────┘                         │
└──────────────────────────────────────────────────────────────────────┘
```

---

### 7.3 Component Descriptions

#### 7.3.1 Filter — `filters/olya_video.py`

```python
from aiogram.filters import BaseFilter
from aiogram.types import Message, MessageOriginChannel
from config.settings import settings

class OlyaVideoFilter(BaseFilter):
    """Filter: video from @ole4444444ka + optional SaveAsBot detection.
    
    Returns dict with detection info on match, False otherwise.
    """
    
    def __init__(self) -> None:
        self._user_id = settings.OLYA_USER_ID
        self._saveasbot_channel_ids = set(settings.OLYA_SAVEASBOT_CHANNEL_IDS)
        self._caption_text = settings.OLYA_CAPTION_TEXT
        self._caption_enabled = settings.OLYA_CAPTION_ENABLED
        self._repost_enabled = settings.OLYA_REPOST_ENABLED
        self._media_type = settings.OLYA_MEDIA_TYPE
        self._always_send = settings.OLYA_ALWAYS_SEND
    
    async def __call__(self, message: Message) -> dict[str, bool] | bool:
        # 1. User check
        if message.from_user is None:
            return False
        if message.from_user.id != self._user_id:
            return False
        
        # 2. Media type check
        if not self._check_media_type(message):
            return False
        
        # 3. Detection
        is_saveasbot = False
        matched_caption = False
        
        if self._repost_enabled:
            is_saveasbot = self._check_repost(message)
        
        if self._caption_enabled:
            matched_caption = self._check_caption(message)
        
        # 4. Trigger decision
        if is_saveasbot or matched_caption or self._always_send:
            return {
                "is_saveasbot": is_saveasbot,
                "matched_caption": matched_caption,
            }
        
        return False
```

**`_check_media_type(message) -> bool`:**
- `OLYA_MEDIA_TYPE == "video"` → `message.video is not None`
- `OLYA_MEDIA_TYPE == "photo"` → `message.photo is not None`
- `OLYA_MEDIA_TYPE == "any"` → `True` (any media or text)

**`_check_repost(message) -> bool`:**
- Проверяет `message.forward_origin` — является ли `MessageOriginChannel` с ID из `_saveasbot_channel_ids`

**`_check_caption(message) -> bool`:**
- Проверяет `message.caption` — содержит ли `_caption_text` как подстроку

#### 7.3.2 Service — `services/olya_relay.py`

```python
import logging
import random
import time
from pathlib import Path

from aiogram import Bot
from aiogram.types import FSInputFile

logger = logging.getLogger(__name__)

MEDIA_PHOTO = "photo"
MEDIA_VIDEO = "video"
MEDIA_ANIMATION = "animation"
MEDIA_AUDIO = "audio"
MEDIA_VOICE = "voice"

_IMAGE_EXTENSIONS: set[str] = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
_VIDEO_EXTENSIONS: set[str] = {".mp4", ".mov", ".webm"}
_AUDIO_EXTENSIONS: set[str] = {".mp3"}
_VOICE_EXTENSIONS: set[str] = {".ogg"}


class OlyaRelay:
    """Sends random media files from olya media directory.
    
    Key differences from CommonRelay:
    - NO ReplyParameters — plain send, no reply/quote
    - Single cooldown (no per-type cooldown)
    - User-specific (one user only)
    - Scans a flat directory (not subdir-based like common/otboy/, common/danger/)
    """
    
    def __init__(
        self,
        bot: Bot,
        cooldown_seconds: float,
        media_base: str,
    ) -> None:
        self._bot = bot
        self._cooldown_seconds = cooldown_seconds
        self._media_base = media_base
        self._cooldowns: dict[int, float] = {}
    
    def _detect_media_type(self, filepath: Path) -> str | None:
        """Detect media type from extension and filename.
        
        GIF detection: if filename contains "gif" anywhere → animation.
        Matches CommonRelay pattern: check _gif, gif prefix, .gif.
        """
        ext = filepath.suffix.lower()
        if ext in _IMAGE_EXTENSIONS:
            return MEDIA_PHOTO
        if ext in _VIDEO_EXTENSIONS:
            fname = filepath.name.lower()
            if "_gif" in fname or fname.startswith("gif") or ".gif." in fname:
                return MEDIA_ANIMATION
            return MEDIA_VIDEO
        if ext in _AUDIO_EXTENSIONS:
            return MEDIA_AUDIO
        if ext in _VOICE_EXTENSIONS:
            return MEDIA_VOICE
        return None
    
    def _scan_directory(self) -> list[tuple[Path, str]]:
        """Scan media_base for all supported media files.
        
        Returns list of (path, media_type). Empty if dir missing or no files.
        Per-entry OSError handling (same pattern as CommonRelay Epic 18 fix).
        """
        base = Path(self._media_base)
        if not base.exists():
            logger.warning("OlyaRelay: directory not found %s", base)
            return []
        
        files: list[tuple[Path, str]] = []
        for entry in base.iterdir():
            try:
                if not entry.is_file():
                    continue
                media_type = self._detect_media_type(entry)
                if media_type is not None:
                    files.append((entry, media_type))
                else:
                    logger.debug(
                        "OlyaRelay: skipping unsupported file %s", entry.name
                    )
            except OSError:
                logger.warning(
                    "OlyaRelay: cannot access entry %s — skipping", entry
                )
                continue
        
        logger.info(
            "OlyaRelay: scanned %s — found %d supported files: %s",
            base, len(files),
            [(f.name, mt) for f, mt in files],
        )
        
        if not files:
            logger.warning("OlyaRelay: no supported media files in %s", base)
        
        return files
    
    async def _send_file(
        self, chat_id: int, filepath: Path, media_type: str,
    ) -> None:
        """Send file via bot.send_* WITHOUT ReplyParameters (plain send)."""
        input_file = FSInputFile(str(filepath))
        
        if media_type == MEDIA_PHOTO:
            await self._bot.send_photo(chat_id=chat_id, photo=input_file)
        elif media_type == MEDIA_VIDEO:
            await self._bot.send_video(chat_id=chat_id, video=input_file)
        elif media_type == MEDIA_ANIMATION:
            await self._bot.send_animation(chat_id=chat_id, animation=input_file)
        elif media_type == MEDIA_AUDIO:
            await self._bot.send_audio(chat_id=chat_id, audio=input_file)
        elif media_type == MEDIA_VOICE:
            await self._bot.send_voice(chat_id=chat_id, voice=input_file)
        else:
            raise ValueError(f"OlyaRelay: unknown media_type: {media_type}")
    
    async def send_olya(self, chat_id: int) -> bool:
        """Main entry point: cooldown check → pick random file → send.
        
        Returns True if media was sent, False if blocked/empty/error.
        """
        now = time.monotonic()
        
        if self._cooldown_seconds > 0:
            last_sent = self._cooldowns.get(chat_id)
            if last_sent is not None:
                elapsed = now - last_sent
                if elapsed < self._cooldown_seconds:
                    logger.info(
                        "OlyaRelay: cooldown_active | chat_id=%s | "
                        "elapsed=%.1fs | remaining=%.1fs",
                        chat_id, elapsed,
                        self._cooldown_seconds - elapsed,
                    )
                    return False
        
        try:
            files = self._scan_directory()
        except (PermissionError, OSError):
            logger.exception(
                "OlyaRelay: scan error | chat_id=%s", chat_id
            )
            return False
        
        if not files:
            return False
        
        filepath, media_type = random.choice(files)
        logger.info(
            "OlyaRelay: picked %s (%s) | chat_id=%s",
            filepath.name, media_type, chat_id,
        )
        
        try:
            await self._send_file(chat_id, filepath, media_type)
            self._cooldowns[chat_id] = now
            logger.info(
                "OlyaRelay: sent | chat_id=%s | file=%s | type=%s",
                chat_id, filepath.name, media_type,
            )
            return True
        except Exception:
            logger.exception(
                "OlyaRelay: send failed | chat_id=%s | file=%s | type=%s",
                chat_id, filepath.name, media_type,
            )
            return False
```

#### 7.3.3 Handler — `handlers/olya.py`

```python
"""Epic 19 — Olya Service.

Single-handler router:
  1. olya_handler: catches video from @ole4444444ka → random media from olya/cringe/

Registered at position 4d between common_router and slavik_router.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aiogram import Router, types
from aiogram.dispatcher.event.bases import UNHANDLED

from filters.olya_video import OlyaVideoFilter

if TYPE_CHECKING:
    from services.olya_relay import OlyaRelay

logger = logging.getLogger(__name__)

olya_router = Router(name="olya")

_service: OlyaRelay | None = None


def setup_olya(service: OlyaRelay) -> None:
    """Inject OlyaRelay dependency. Called from bot.on_startup()."""
    global _service
    _service = service
    logger.info("Olya Service: relay injected")


@olya_router.message(OlyaVideoFilter())
async def olya_handler(
    message: types.Message,
    is_saveasbot: bool,
    matched_caption: bool,
) -> None:
    """Handle video from Olya user → send random media without reply."""
    if _service is None:
        logger.error(
            "Olya Service: relay not initialized — skipping | "
            "chat_id=%s | message_id=%s",
            message.chat.id, message.message_id,
        )
        return

    logger.info(
        "Olya Service: triggered | chat_id=%s | msg_id=%s | "
        "is_saveasbot=%s | matched_caption=%s",
        message.chat.id, message.message_id,
        is_saveasbot, matched_caption,
    )

    try:
        await _service.send_olya(message.chat.id)
    except Exception:
        logger.exception(
            "Olya Service: handler failed | chat_id=%s | message_id=%s",
            message.chat.id, message.message_id,
        )
    return UNHANDLED
```

---

### 7.4 Configuration Table

| # | Field | Type | Default | Env Variable | Description |
|---|-------|------|---------|-------------|-------------|
| 1 | `OLYA_ENABLED` | `bool` | `True` | `OLYA_ENABLED` | Feature toggle — disables entire router registration |
| 2 | `OLYA_USER_ID` | `int` | `834424825` | `OLYA_USER_ID` | Target user ID (@ole4444444ka) |
| 3 | `OLYA_COOLDOWN_SECONDS` | `float` | `60.0` | `OLYA_COOLDOWN_SECONDS` | Single cooldown between sends per chat |
| 4 | `OLYA_MEDIA_BASE` | `str` | `"media/olya/cringe"` | `OLYA_MEDIA_BASE` | Directory for media files |
| 5 | `OLYA_SAVEASBOT_CHANNEL_IDS` | `tuple[int, ...]` | `(523131145,)` | `OLYA_SAVEASBOT_CHANNEL_IDS` | Comma-separated channel IDs for repost detection |
| 6 | `OLYA_CAPTION_ENABLED` | `bool` | `True` | `OLYA_CAPTION_ENABLED` | Enable caption text detection |
| 7 | `OLYA_CAPTION_TEXT` | `str` | `"Спасибо, что пользуетесь - @SaveAsBot'ом"` | `OLYA_CAPTION_TEXT` | Text to match in message caption |
| 8 | `OLYA_REPOST_ENABLED` | `bool` | `True` | `OLYA_REPOST_ENABLED` | Enable repost-from-SaveAsBot detection |
| 9 | `OLYA_MEDIA_TYPE` | `str` | `"video"` | `OLYA_MEDIA_TYPE` | Media type filter: `"video"`, `"photo"`, or `"any"` |
| 10 | `OLYA_ALWAYS_SEND` | `bool` | `True` | `OLYA_ALWAYS_SEND` | If True, always sends from this user regardless of conditions |

**`config/settings.py` additions** (after existing Olya config or at end of `Settings`):

```python
# ── Olya Service (Epic 19) ──
OLYA_ENABLED: bool = os.getenv("OLYA_ENABLED", "True").lower() in ("true", "1", "yes")
OLYA_USER_ID: int = _env_int("OLYA_USER_ID", 834424825)
OLYA_COOLDOWN_SECONDS: float = _env_float("OLYA_COOLDOWN_SECONDS", 60.0)
OLYA_MEDIA_BASE: str = os.getenv("OLYA_MEDIA_BASE", "media/olya/cringe")
OLYA_SAVEASBOT_CHANNEL_IDS: tuple[int, ...] = tuple(
    int(x.strip()) for x in os.getenv("OLYA_SAVEASBOT_CHANNEL_IDS", "523131145").split(",") if x.strip()
)
OLYA_CAPTION_ENABLED: bool = os.getenv("OLYA_CAPTION_ENABLED", "True").lower() in ("true", "1", "yes")
OLYA_CAPTION_TEXT: str = os.getenv("OLYA_CAPTION_TEXT", "Спасибо, что пользуетесь - @SaveAsBot'ом")
OLYA_REPOST_ENABLED: bool = os.getenv("OLYA_REPOST_ENABLED", "True").lower() in ("true", "1", "yes")
OLYA_MEDIA_TYPE: str = os.getenv("OLYA_MEDIA_TYPE", "video")
OLYA_ALWAYS_SEND: bool = os.getenv("OLYA_ALWAYS_SEND", "True").lower() in ("true", "1", "yes")
```

---

### 7.5 Router Position and Propagation Flow

```
Position 0:  admin_commands_router     (/deadpage, /alangreet)
Position 1:  slava_presence_router     (ChatMemberUpdated: Slava join/leave)
Position 1b: alan_greeting_router      (ChatMemberUpdated: Alan join → greeting)
Position 2:  kostik_router             (UserIdFilter: Kostik → probability reply)
Position 3:  alan_router               (UserIdFilter: Alan → reply engine)
Position 4:  dead_page_router          (F.forward_origin: @d_pages reposts)
Position 4b: war_alert_router          (WarWordFilter + TargetChannelFilter)
Position 4c: common_router             (OtboyWordFilter + DangerWordFilter + mimic)
Position 4d: olya_router               ← NEW: OlyaVideoFilter → random media
Position 5:  slavik_router             (UserIdFilter: Slava → kucha + catchall)
Position 6:  vasya_router              (Text filters, no user restriction)
```

**Propagation note:** `olya_router` positioned at 4d — after `common_router` but before `slavik_router`. All handlers return `UNHANDLED` to continue propagation. Even when Olya handler fires and sends media, the event continues to `slavik_router` and `vasya_router`. This is safe because:
- `slavik_router` has `UserIdFilter(SLAVIK_USER_ID)` — won't match Olya's messages
- `vasya_router` has text-based filters — unlikely to match a video message

**registration guard in `bot.py`:**
```python
# 4d. Olya Service (Epic 19) — video from @ole4444444ka → random media (plain send)
if settings.OLYA_ENABLED:
    from handlers.olya import olya_router, setup_olya
    from services.olya_relay import OlyaRelay
    
    olya_relay = OlyaRelay(
        bot,
        cooldown_seconds=settings.OLYA_COOLDOWN_SECONDS,
        media_base=settings.OLYA_MEDIA_BASE,
    )
    setup_olya(olya_relay)
    dp.include_router(olya_router)
    logger.info("Olya Service (Epic 19) registered")
```

---

### 7.6 Data Flow Diagram

```
 ┌───────────────────────────────────────────────────────────────┐
 │  MESSAGE FLOW                                                 │
 │                                                               │
 │  @ole4444444ka sends video in chat                            │
 │       │                                                       │
 │       ▼                                                       │
 │  ┌──────────┐    ┌──────────┐    ┌──────────┐                │
 │  │ dead_page │───→│war_alert │───→│ common   │                │
 │  │  router   │    │  router  │    │  router  │                │
 │  │  (pos 4)  │    │  (pos 4b)│    │  (pos 4c)│                │
 │  └─────┬─────┘    └─────┬────┘    └─────┬────┘                │
 │        │               │              │                       │
 │        ▼               ▼              ▼                       │
 │   no match /       no match /     no match /                  │
 │   UNHANDLED        UNHANDLED      UNHANDLED                   │
 │                                                               │
 │        ┌──────────────────┐                                   │
 │        │  olya_router     │  ← NEW (pos 4d)                   │
 │        │  ┌─────────────┐ │                                   │
 │        │  │OlyaVideo    │ │                                   │
 │        │  │Filter       │ │                                   │
 │        │  └──────┬──────┘ │                                   │
 │        │         │        │                                   │
 │        │    ┌────▼─────┐  │                                   │
 │        │    │ MATCH?    │  │                                   │
 │        │    │ user=OK   │  │                                   │
 │        │    │ media=OK  │  │                                   │
 │        │    │ trigger=OK│  │                                   │
 │        │    └────┬─────┘  │                                   │
 │        │         │ YES    │                                   │
 │        │    ┌────▼─────┐  │                                   │
 │        │    │olya_     │  │                                   │
 │        │    │handler() │  │                                   │
 │        │    └────┬─────┘  │                                   │
 │        └─────────┼────────┘                                   │
 │                  │                                            │
 │                  ▼                                            │
 │        ┌─────────────────┐                                    │
 │        │  OlyaRelay      │                                    │
 │        │  ┌────────────┐ │                                    │
 │        │  │ cooldown?  │─┤─── YES → return False             │
 │        │  │ scan dir   │ │                                    │
 │        │  │ random pick│ │                                    │
 │        │  │ send plain │ │                                    │
 │        │  └────────────┘ │                                    │
 │        └────────┬────────┘                                    │
 │                 │                                             │
 │                 ▼                                             │
 │        ┌─────────────────┐                                    │
 │        │  bot.send_video │  ← NO ReplyParameters              │
 │        │  bot.send_photo │                                    │
 │        │  bot.send_anim  │                                    │
 │        │  ...            │                                    │
 │        └────────┬────────┘                                    │
 │                 │                                             │
 │                 ▼                                             │
 │        ┌─────────────────┐                                    │
 │        │  return         │                                    │
 │        │  UNHANDLED      │  ← propagation continues           │
 │        └────────┬────────┘                                    │
 │                 │                                             │
 │                 ▼                                             │
 │        ┌─────────────────┐                                    │
 │        │  slavik_router  │  (pos 5)                           │
 │        │  vasya_router   │  (pos 6)                           │
 │        └─────────────────┘                                    │
 └───────────────────────────────────────────────────────────────┘
```

---

### 7.7 Key Differences from CommonRelay

| Aspect | CommonRelay | OlyaRelay |
|--------|------------|-----------|
| **Send style** | Reply with `ReplyParameters(message_id, quote=word)` | **Plain send** — no `ReplyParameters` |
| **Cooldown** | Dual: shared + danger-specific | **Single**: one cooldown value |
| **Users** | Any user | **One user only** (834424825) |
| **Trigger** | Word-based (otboy, danger) | **Media-based** (video/photo from user) + config toggles |
| **Directory** | `media/common/{subdir}/` (otboy/, danger/) | **Flat**: `media/olya/cringe/` |
| **Filter returns** | `{"matched_word": str}` | **`{"is_saveasbot": bool, "matched_caption": bool}`** |
| **Config complexity** | 5 fields | **10 fields** (multiple boolean toggles) |
| **reply_to_message_id** | Used everywhere | **Never used** |

**Mandatory constraint:** Olya handler/send MUST NOT reference `message.message_id`, `ReplyParameters`, `reply_to_message_id`, or any reply mechanism. Send is always `bot.send_*(chat_id=..., ...=FSInputFile(...))`.

---

### 7.8 Testing Strategy

#### 7.8.1 Filter Tests (`TestOlyaVideoFilter`)

| ID | Test | Expected |
|----|------|----------|
| T-F1 | Message from user 834424825 with video | `True`, returns `dict` |
| T-F2 | Message from different user with video | `False` |
| T-F3 | Message from user 834424825, no media (text only), `MEDIA_TYPE=video` | `False` |
| T-F4 | Message from user 834424825 with photo, `MEDIA_TYPE=photo` | `True` |
| T-F5 | Message from user 834424825 with photo, `MEDIA_TYPE=any` | `True` |
| T-F6 | Message from user 834424825, caption contains SAVEAASBOT text, `CAPTION_ENABLED=True` | `True`, `matched_caption=True` |
| T-F7 | Message from user 834424825, caption contains SAVEAASBOT text, `CAPTION_ENABLED=False` | Depends on `ALWAYS_SEND` |
| T-F8 | Message from user 834424825, forward_origin is SaveAsBot channel (523131145), `REPOST_ENABLED=True` | `True`, `is_saveasbot=True` |
| T-F9 | Message from user 834424825, forward_origin is SaveAsBot channel, `REPOST_ENABLED=False` | Depends on `ALWAYS_SEND` |
| T-F10 | Message from user 834424825, forward_origin is OTHER channel | Depends on `ALWAYS_SEND` |
| T-F11 | Message from user 834424825, video, no caption, no repost, `ALWAYS_SEND=True` | `True`, both flags False |
| T-F12 | Message from user 834424825, video, no caption, no repost, `ALWAYS_SEND=False` | `False` |
| T-F13 | Message from user 834424825, no `from_user` (should never happen) | `False` |

#### 7.8.2 Service Tests (`TestOlyaRelay`)

| ID | Test | Expected |
|----|------|----------|
| T-S1 | `_scan_directory` with 3 .mp4 files in media dir | Returns 3 tuples |
| T-S2 | `_scan_directory` with mixed types (.jpg, .mp4, .ogg, .mp3) | All detected correctly |
| T-S3 | `_scan_directory` with .gif file (e.g. `cringe_gif.mp4`) | Detected as `animation` |
| T-S4 | `_scan_directory` with empty directory | Returns `[]`, WARNING logged |
| T-S5 | `_scan_directory` with no directory | Returns `[]`, WARNING logged |
| T-S6 | `_scan_directory` with unsupported file (.txt, .pdf) | Skipped, DEBUG logged |
| T-S7 | `_scan_directory` with per-entry OSError | Bad entry skipped, good entries returned |
| T-S8 | `_detect_media_type` photo (.jpg, .jpeg, .png, .webp, .bmp) | `MEDIA_PHOTO` |
| T-S9 | `_detect_media_type` video (.mp4, .mov, .webm) | `MEDIA_VIDEO` |
| T-S10 | `_detect_media_type` gif animation (`_gif.mp4`, `gif_name.mp4`, `name.gif.mp4`) | `MEDIA_ANIMATION` |
| T-S11 | `_detect_media_type` audio (.mp3) | `MEDIA_AUDIO` |
| T-S12 | `_detect_media_type` voice (.ogg) | `MEDIA_VOICE` |
| T-S13 | `_detect_media_type` unsupported (.txt) | `None` |
| T-S14 | `_detect_media_type` false positive: `gift.mp4` | `MEDIA_VIDEO` (not animation) |
| T-S15 | `send_olya` with files → cooldown check → random.choice → send | Returns `True`, file sent |
| T-S16 | `send_olya` during cooldown | Returns `False`, not sent |
| T-S17 | `send_olya` after cooldown expires | Returns `True`, sent |
| T-S18 | `send_olya` with cooldown=0 | Always sends (no blocking) |
| T-S19 | `send_olya` with empty directory | Returns `False` |
| T-S20 | `send_olya` → send fails (e.g. TelegramError) | Returns `False`, exception logged |
| T-S21 | `send_olya` → scan fails (PermissionError) | Returns `False`, exception logged |
| T-S22 | `_send_file` with `MEDIA_PHOTO` | Calls `bot.send_photo(chat_id, photo=...)` — no ReplyParameters |
| T-S23 | `_send_file` with `MEDIA_VIDEO` | Calls `bot.send_video(chat_id, video=...)` — no ReplyParameters |
| T-S24 | `_send_file` with `MEDIA_ANIMATION` | Calls `bot.send_animation(chat_id, animation=...)` — no ReplyParameters |
| T-S25 | `_send_file` with `MEDIA_AUDIO` | Calls `bot.send_audio(chat_id, audio=...)` — no ReplyParameters |
| T-S26 | `_send_file` with `MEDIA_VOICE` | Calls `bot.send_voice(chat_id, voice=...)` — no ReplyParameters |
| T-S27 | `_send_file` with unknown type | Raises `ValueError` |
| T-S28 | Random selection: 3 files, 100 calls | All files selected (uniform distribution, no starvation) |

#### 7.8.3 Handler Tests (`TestOlyaHandler`)

| ID | Test | Expected |
|----|------|----------|
| T-H1 | Handler calls `_service.send_olya(message.chat.id)` | `send_olya` called once |
| T-H2 | `_service is None` (not initialized) | Error logged, no send called |
| T-H3 | `_service.send_olya` raises `Exception` | Exception caught and logged |
| T-H4 | Handler returns `UNHANDLED` | Event propagation continues |
| T-H5 | Filter returns `False` → handler not called | Only filter checked |

#### 7.8.4 Integration Tests

| ID | Test | Expected |
|----|------|----------|
| T-I1 | `OLYA_ENABLED=False` → router not registered | No Olya handler in dispatcher |
| T-I2 | Full flow: message → filter → handler → relay → send | Media sent without reply |
| T-I3 | Full flow: message matches Olya AND Slava | Both handlers fire (Olya at 4d, Slava at 5) |

---

### 7.9 Deployment Notes

#### 7.9.1 File Structure

```
media/olya/cringe/          ← NEW directory (created on deploy)
├── cringe_01.mp4           ← example video
├── cringe_02_gif.mp4       ← example animation (contains "gif")
├── cringe_03.jpg           ← example photo
└── ...                     ← any supported media type
```

#### 7.9.2 New Files Created

| File | Purpose |
|------|---------|
| `filters/olya_video.py` | `OlyaVideoFilter` — user + media + trigger detection |
| `services/olya_relay.py` | `OlyaRelay` — directory scan, media type detection, plain send |
| `handlers/olya.py` | `olya_router` + `setup_olya()` + `olya_handler` |
| `tests/test_olya.py` | Unit + integration tests (see §7.8) |

#### 7.9.3 Existing Files Modified

| File | Changes |
|------|---------|
| `config/settings.py` | Add 10 Olya fields (§7.4) |
| `bot.py` | Import olya_router/OlyaRelay/setup_olya; create + inject in `on_startup()`; `dp.include_router(olya_router)` at position 4d with `OLYA_ENABLED` guard |
| `.env.example` | Add Olya environment variables |

#### 7.9.4 Backward Compatibility

- All new code behind feature toggle `OLYA_ENABLED=True` (default)
- If disabled (`OLYA_ENABLED=False`): no imports, no router registration, zero overhead
- If enabled but directory empty: graceful degradation (WARNING log, no send)
- Existing services (common, slavik, etc.) untouched
- All handlers return `UNHANDLED` — no propagation interference

#### 7.9.5 Rollback

To disable Olya service:
- Set `OLYA_ENABLED=False` in `.env` and restart bot
- OR remove `media/olya/cringe/` directory (graceful empty dir handling)

---

@Orchestrator Epic 19 architecture ready, passing the baton.

---

## Section 28: Epic 20 — Slavik Random Media Enhancement (v2.18.0)

> **Дата:** 2026-08-02
> **Статус:** Архитектурный дизайн. Реализация НЕ начата.
> **Затрагиваемые файлы:** `handlers/slavik.py` (3 функции: `_detect_slavik_media_type`, `_send_slavik_media`, `_pick_random_slavik_media`). Никаких новых файлов, изменений роутера или БД.

---

### 28.1 Overview and Scope

Epic 20 расширяет поддержку медиа-типов в slavik random media picker (`handlers/slavik.py`) до полного паритета с `CommonRelay` (`services/common_relay.py`). Текущая реализация поддерживает только photo, video и animation. Цель — добавить audio, voice и document (как fallback для любых неподдерживаемых форматов), а также усилить GIF-детекцию.

**Критическое ограничение:** изменения затрагивают **ТОЛЬКО** `handlers/slavik.py`. Никакие другие файлы не модифицируются. Новые файлы не создаются. Роутеры, настройки, БД — без изменений.

**Связанные эпики:**
- Epic 16 (Slavik Random Media Picker) — реализован в текущей версии, заложил основу (photo/video/animation)
- Epic 18 (Danger Service Fixes) — улучшил GIF-детекцию и per-entry OSError handling в CommonRelay
- Epic 19 (Olya Service) — содержит `OlyaRelay._detect_media_type()` с полным набором типов (включая audio/voice)

---

### 28.2 Design Decisions (D49–D53)

#### D49: Reply Behaviour — No Changes Needed (CONFIRMED)

`message.answer_*()` методы в aiogram 3.x автоматически отвечают на оригинальное сообщение **без цитирования** (без вызова `send_*` с `ReplyParameters`). Это стандартное поведение Telegram Bot API для `answer_*` шорткатов — `reply_to_message_id` подставляется автоматически, `quote` отсутствует.

В отличие от `CommonRelay` и `OlyaRelay`, которые используют `bot.send_*()` (требуется ручная передача `chat_id` и опциональных `ReplyParameters`), slavik handler использует `message.answer_*()`. Разница:

| Метод | Тип вызова | Reply поведение | Quote |
|-------|-----------|----------------|-------|
| `message.answer_photo(photo=...)` | Shortcut | Auto-reply (без quote) | ❌ |
| `message.answer_video(video=...)` | Shortcut | Auto-reply (без quote) | ❌ |
| `message.answer_animation(animation=...)` | Shortcut | Auto-reply (без quote) | ❌ |
| `message.answer_audio(audio=...)` | Shortcut | Auto-reply (без quote) | ❌ |
| `message.answer_voice(voice=...)` | Shortcut | Auto-reply (без quote) | ❌ |
| `message.answer_document(document=...)` | Shortcut | Auto-reply (без quote) | ❌ |
| `bot.send_photo(chat_id=..., reply_parameters=...)` | Raw API | Ручное управление | ✅ (если передан) |

**Вердикт:** reply-поведение slavik handler **уже корректно**. Никаких изменений не требуется. `message.answer_*` методы делают именно то, что нужно — reply без quote.

---

#### D50: Media Type Detection Parity with CommonRelay

Текущая `_detect_slavik_media_type()` поддерживает 3 типа (photo, video, animation). `CommonRelay._detect_media_type()` поддерживает 5 типов (photo, video, animation, audio, voice). **Расширяем до 6 типов** — добавляем document как универсальный fallback.

**Статус расширений:**

| Тип | Расширения | Текущий slavik | CommonRelay | Epic 20 |
|-----|-----------|:---:|:---:|:---:|
| photo | .jpg, .jpeg, .png, .webp, .bmp | ✅ | ✅ | ✅ |
| video | .mp4, .mov, .webm (без "gif") | ✅ | ✅ | ✅ |
| animation | .mp4, .mov, .webm (с "gif") | ✅ | ✅ | ✅ |
| audio | .mp3 | ❌ | ✅ | ✅ (NEW) |
| voice | .ogg | ❌ | ✅ | ✅ (NEW) |
| document | всё остальное (fallback) | ❌ | ❌ | ✅ (NEW) |

**Архитектурное обоснование document-fallback:**
- CommonRelay возвращает `None` для неподдерживаемых форматов → файл игнорируется при сканировании
- Slavik handler НЕ может позволить себе игнорировать файлы — если пользователь положил `.pdf` или `.mkv` в `slavik_random/`, это валидный медиа-файл, который должен быть отправлен
- `message.answer_document()` отправляет любой файл как документ — Telegram сам определит MIME-тип
- Это делает slavik random media более устойчивым (robust) — **любой** файл в директории будет отправлен

---

#### D51: GIF Detection — Switch from `filepath.stem` to `filepath.name`

**Текущий код** (`handlers/slavik.py` строка 36):
```python
if "gif" in filepath.stem.lower():
    return "animation"
```

**Проблемы:**
1. Несогласованность с CommonRelay — тот использует `filepath.name.lower()` (после Epic 18 fix)
2. `filepath.stem` обрезает расширение: `file.gift.mp4` → stem = `file.gift` → содержит "gif" → **ложное срабатывание** (gift ≠ gif)
3. Не проверяет word-boundary — любой "gif" в любом месте имени считается анимацией

**Новый код (целевой):**
```python
if ext in _VIDEO_EXTENSIONS:
    fname = filepath.name.lower()
    if "_gif" in fname or fname.startswith("gif") or ".gif." in fname:
        return "animation"
    return "video"
```

**Правила матчинга (паритет с CommonRelay):**

| Имя файла | `_gif` | `startswith("gif")` | `.gif.` | Результат |
|-----------|:------:|:-------------------:|:-------:|-----------|
| `slavic_chlen.mp4` | ❌ | ❌ | ❌ | video |
| `danger_02_gif.mp4` | ✅ | ❌ | ✅ | animation |
| `cringe_gif.mp4` | ✅ | ❌ | ❌ | animation |
| `gif_animation.mp4` | ❌ | ✅ | ❌ | animation |
| `some.gif.mp4` | ❌ | ❌ | ✅ | animation |
| `file.gift.mp4` | ❌ | ❌ | ❌ | **video** (корректно!) |
| `gift_box.mp4` | ❌ | ❌ | ❌ | video |

**Почему `filepath.name` вместо `filepath.stem`:**
- `Path("file.gift.mp4").stem` → `"file.gift"` → содержит "gif" — ложный animation
- `Path("file.gift.mp4").name` → `"file.gift.mp4"` → `.gif.` не матчит, `_gif` не матчит, `startswith("gif")` не матчит → video (корректно)
- `Path("danger_02_gif.mp4").name` → `"danger_02_gif.mp4"` → `_gif` матчит → animation (корректно)

---

#### D52: Fallback to Document — Robustness for Unsupported Formats

**Текущее поведение:**
- `_detect_slavik_media_type()` возвращает `None` для неподдерживаемых расширений
- `_pick_random_slavik_media()` фильтрует `media_type is not None` → неподдерживаемые файлы **игнорируются**
- `_send_slavik_media()` имеет `else`-ветку с fallback на `answer_photo` (хрупко — может упасть для не-photo файлов)

**Новое поведение:**
- `_detect_slavik_media_type()` возвращает `"document"` для ВСЕХ неподдерживаемых расширений (вместо `None`)
- `_pick_random_slavik_media()` включает ВСЕ файлы (фильтр `media_type is not None` больше не отсекает — теперь `"document"` — валидный тип)
- `_send_slavik_media()` вызывает `message.answer_document(document=input_file)` для типа `"document"`
- Убирается хрупкий `else` → `answer_photo` fallback

**Пример:** пользователь положил `slavik_ebook.pdf` в `slavik_random/`:
- Было: `_detect_slavik_media_type()` → `None` → файл игнорируется при сканировании
- Стало: `_detect_slavik_media_type()` → `"document"` → файл выбирается → `message.answer_document(document=FSInputFile("slavik_ebook.pdf"))`

---

#### D53: Code Changes Scope — Only 3 Functions in 1 File

| Изменение | Файл | Функция | Тип изменения |
|-----------|------|---------|--------------|
| Добавить audio/voice/document детекцию + hardened GIF | `handlers/slavik.py` | `_detect_slavik_media_type()` | Расширение логики |
| Добавить audio/voice/document send-ветки | `handlers/slavik.py` | `_send_slavik_media()` | Добавление elif-веток |
| Включить все файлы (убрать фильтр по None) + per-entry OSError | `handlers/slavik.py` | `_pick_random_slavik_media()` | Изменение фильтрации + robustness |

**Что НЕ меняется:**
- `config/settings.py` — нет новых env-переменных
- `.env.example` — без изменений
- `bot.py` — нет изменений в регистрации роутеров
- Роутер `slavik_router` — позиция, фильтры, хэндлеры — без изменений
- `slavik_catchall_handler` — логика вызова `_pick_random_slavik_media()` и `_send_slavik_media()` остаётся прежней
- БД — `slavic_photo_count_tick` не меняется
- `media/slavik/` структура — не меняется

---

### 28.3 Media Type Detection Matrix

Полная матрица: расширение → тип медиа (после Epic 20):

| Расширение | Условие | Тип | Send метод |
|-----------|---------|-----|-----------|
| `.jpg`, `.jpeg`, `.png`, `.webp`, `.bmp` | — | `photo` | `message.answer_photo(photo=input_file)` |
| `.mp4`, `.mov`, `.webm` | имя НЕ содержит "gif" | `video` | `message.answer_video(video=input_file)` |
| `.mp4`, `.mov`, `.webm` | имя содержит "gif" (word-boundary) | `animation` | `message.answer_animation(animation=input_file)` |
| `.mp3` | — | `audio` | `message.answer_audio(audio=input_file)` |
| `.ogg` | — | `voice` | `message.answer_voice(voice=input_file)` |
| любое другое | — | `document` | `message.answer_document(document=input_file)` |

**GIF word-boundary правила:**
- `"_gif"` в имени → animation (e.g. `slavic_gif.mp4`)
- имя начинается с `"gif"` → animation (e.g. `gif_slavic.mp4`)
- `".gif."` в имени → animation (e.g. `slavic.gif.mp4`)

---

### 28.4 Function-Level Before/After

#### 28.4.1 `_detect_slavik_media_type(filepath: Path) -> str`

**Было (3 типа, возвращает None для unsupported):**
```python
def _detect_slavik_media_type(filepath: Path) -> str | None:
    ext = filepath.suffix.lower()
    if ext in _IMAGE_EXTENSIONS:
        return "photo"
    if ext in _VIDEO_EXTENSIONS:
        if "gif" in filepath.stem.lower():
            return "animation"
        return "video"
    return None
```

**Стало (6 типов, ВСЕГДА возвращает str):**
```python
_IMAGE_EXTENSIONS: set[str] = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
_VIDEO_EXTENSIONS: set[str] = {".mp4", ".mov", ".webm"}
_AUDIO_EXTENSIONS: set[str] = {".mp3"}
_VOICE_EXTENSIONS: set[str] = {".ogg"}

def _detect_slavik_media_type(filepath: Path) -> str:
    ext = filepath.suffix.lower()
    if ext in _IMAGE_EXTENSIONS:
        return "photo"
    if ext in _VIDEO_EXTENSIONS:
        fname = filepath.name.lower()
        if "_gif" in fname or fname.startswith("gif") or ".gif." in fname:
            return "animation"
        return "video"
    if ext in _AUDIO_EXTENSIONS:
        return "audio"
    if ext in _VOICE_EXTENSIONS:
        return "voice"
    return "document"
```

**Ключевое изменение сигнатуры:** возвращаемый тип `str | None` → `str`. Функция больше не возвращает `None` — любой файл получает валидный тип.

#### 28.4.2 `_send_slavik_media(message, filepath, media_type) -> None`

**Было (3 send-ветки + хрупкий photo-fallback):**
```python
async def _send_slavik_media(message, filepath, media_type):
    input_file = FSInputFile(str(filepath))
    if media_type == "photo":
        await message.answer_photo(photo=input_file)
    elif media_type == "video":
        await message.answer_video(video=input_file)
    elif media_type == "animation":
        await message.answer_animation(animation=input_file)
    else:
        logger.warning("unknown media type %s", media_type)
        await message.answer_photo(photo=input_file)
```

**Стало (6 send-веток, убран хрупкий fallback):**
```python
async def _send_slavik_media(message, filepath, media_type):
    input_file = FSInputFile(str(filepath))
    if media_type == "photo":
        await message.answer_photo(photo=input_file)
    elif media_type == "video":
        await message.answer_video(video=input_file)
    elif media_type == "animation":
        await message.answer_animation(animation=input_file)
    elif media_type == "audio":
        await message.answer_audio(audio=input_file)
    elif media_type == "voice":
        await message.answer_voice(voice=input_file)
    elif media_type == "document":
        await message.answer_document(document=input_file)
    else:
        logger.warning("Slavic Photo: unknown media type %s for %s", media_type, filepath.name)
```

#### 28.4.3 `_pick_random_slavik_media() -> tuple[Path, str] | None`

**Было (фильтрует unsupported):**
```python
def _pick_random_slavik_media() -> tuple[Path, str] | None:
    media_dir = Path(settings.SLAVIC_RANDOM_DIR)
    if not media_dir.exists():
        return None
    files: list[tuple[Path, str]] = []
    for entry in media_dir.iterdir():
        if not entry.is_file():
            continue
        media_type = _detect_slavik_media_type(entry)
        if media_type is not None:       # ← отсекает unsupported
            files.append((entry, media_type))
    if not files:
        return None
    picked = random.choice(files)
    return picked
```

**Стало (включает все файлы + per-entry OSError handling):**
```python
def _pick_random_slavik_media() -> tuple[Path, str] | None:
    media_dir = Path(settings.SLAVIC_RANDOM_DIR)
    if not media_dir.exists():
        logger.warning("Slavic Photo: directory not found: %s", media_dir)
        return None
    files: list[tuple[Path, str]] = []
    for entry in media_dir.iterdir():
        try:
            if not entry.is_file():
                continue
            media_type = _detect_slavik_media_type(entry)
            files.append((entry, media_type))  # ← всегда добавляем (document fallback)
        except OSError:
            logger.warning(
                "Slavic Photo: cannot access entry %s — skipping", entry
            )
            continue
    if not files:
        logger.warning("Slavic Photo: no files in %s", media_dir)
        return None
    picked = random.choice(files)
    logger.info(
        "Slavic Photo: picked %s (%s) from %d files in %s",
        picked[0].name, picked[1], len(files), media_dir,
    )
    return picked
```

**Изменения:**
1. Убран фильтр `if media_type is not None` — теперь `_detect_slavik_media_type()` ВСЕГДА возвращает валидный тип (document как fallback)
2. Добавлен per-entry `OSError` try/except (паритет с CommonRelay Epic 18 fix)
3. INFO-лог теперь показывает общее количество файлов в директории (полезно для диагностики)

---

### 28.5 Конфигурация (без изменений)

Все существующие env-переменные остаются без изменений:

| Переменная | Значение | Назначение |
|-----------|---------|-----------|
| `SLAVIC_RANDOM_DIR` | `media/slavik/slavik_random` | Директория с медиа (F8 Photo Interval) |
| `SLAVIC_PHOTO_PATH` | (deprecated) | Fallback-путь к одному файлу (если RANDOM_DIR пуст) |
| `SLAVIC_PHOTO_INTERVAL` | `10` | Каждые N ответов Славы — отправка random media |
| `GIF_PATH` | `media/slavic_chlen.mp4` | F3 GIF Interval (НЕ затрагивается Epic 20) |

---

### 28.6 Тест-план (Epic 20)

#### 28.6.1 `_detect_slavik_media_type` — New Types

| ID | Тест | Ожидаемый результат |
|----|------|--------------------|
| T-D1 | `_detect_slavik_media_type(Path("song.mp3"))` | `"audio"` |
| T-D2 | `_detect_slavik_media_type(Path("voice.ogg"))` | `"voice"` |
| T-D3 | `_detect_slavik_media_type(Path("manual.pdf"))` | `"document"` |
| T-D4 | `_detect_slavik_media_type(Path("video.mkv"))` | `"document"` |
| T-D5 | `_detect_slavik_media_type(Path("archive.zip"))` | `"document"` |
| T-D6 | `_detect_slavik_media_type(Path("no_extension"))` | `"document"` |
| T-D7 | `_detect_slavik_media_type(Path("file.txt"))` | `"document"` |

#### 28.6.2 `_detect_slavik_media_type` — GIF Detection (Hardened)

| ID | Тест | Ожидаемый результат |
|----|------|--------------------|
| T-G1 | `_detect_slavik_media_type(Path("slavic_gif.mp4"))` | `"animation"` |
| T-G2 | `_detect_slavik_media_type(Path("gif_animation.mp4"))` | `"animation"` |
| T-G3 | `_detect_slavik_media_type(Path("some.gif.mp4"))` | `"animation"` |
| T-G4 | `_detect_slavik_media_type(Path("file.gift.mp4"))` | `"video"` (НЕ animation — gift ≠ gif) |
| T-G5 | `_detect_slavik_media_type(Path("slavic_chlen.mp4"))` | `"video"` |
| T-G6 | `_detect_slavik_media_type(Path("gift_present.mp4"))` | `"video"` (gift ≠ gif) |

#### 28.6.3 `_detect_slavik_media_type` — Regression (Existing Types)

| ID | Тест | Ожидаемый результат |
|----|------|--------------------|
| T-R1 | `_detect_slavik_media_type(Path("photo.jpg"))` | `"photo"` |
| T-R2 | `_detect_slavik_media_type(Path("image.png"))` | `"photo"` |
| T-R3 | `_detect_slavik_media_type(Path("img.webp"))` | `"photo"` |
| T-R4 | `_detect_slavik_media_type(Path("img.bmp"))` | `"photo"` |
| T-R5 | `_detect_slavik_media_type(Path("video.mp4"))` | `"video"` |
| T-R6 | `_detect_slavik_media_type(Path("clip.mov"))` | `"video"` |
| T-R7 | `_detect_slavik_media_type(Path("anim.webm"))` | `"video"` |
| T-R8 | `_detect_slavik_media_type(Path("anim_gif.webm"))` | `"animation"` (webm + gif) |

#### 28.6.4 `_send_slavik_media` — New Send Methods

| ID | Тест | Ожидаемый результат |
|----|------|--------------------|
| T-S1 | `_send_slavik_media(msg, path, "photo")` | `message.answer_photo()` called |
| T-S2 | `_send_slavik_media(msg, path, "video")` | `message.answer_video()` called |
| T-S3 | `_send_slavik_media(msg, path, "animation")` | `message.answer_animation()` called |
| T-S4 | `_send_slavik_media(msg, path, "audio")` | `message.answer_audio()` called |
| T-S5 | `_send_slavik_media(msg, path, "voice")` | `message.answer_voice()` called |
| T-S6 | `_send_slavik_media(msg, path, "document")` | `message.answer_document()` called |

#### 28.6.5 `_pick_random_slavik_media` — Document Fallback

| ID | Тест | Ожидаемый результат |
|----|------|--------------------|
| T-P1 | Directory with .jpg + .mp3 + .pdf | 3 files returned, types: photo, audio, document |
| T-P2 | Directory with only .pdf files | Returns random .pdf with type "document" |
| T-P3 | Directory with .txt file (no extension logic match) | File included, type "document" |
| T-P4 | Empty directory | Returns `None`, WARNING logged |
| T-P5 | Missing directory | Returns `None`, WARNING logged |
| T-P6 | Directory with 1 .mp4 + 1 broken symlink (OSError) | 1 file returned, WARNING for skipped entry |

#### 28.6.6 Ответ без quote — верификация

| ID | Тест | Ожидаемый результат |
|----|------|--------------------|
| T-Q1 | `message.answer_photo(photo=...)` | `reply_to_message_id` установлен, `reply_parameters` отсутствует, quote не цитируется |
| T-Q2 | `message.answer_document(document=...)` | `reply_to_message_id` установлен, quote отсутствует |
| T-Q3 | `message.answer_audio(audio=...)` | `reply_to_message_id` установлен, quote отсутствует |

---

### 28.7 Риски (Epic 20)

| Риск | Вероятность | Влияние | Митигация |
|------|-----------|---------|-----------|
| `message.answer_document()` не поддерживается старой версией aiogram | Низкая | Высокое | aiogram 3.x поддерживает `answer_document` с версии 3.0; проект использует 3.29.1 |
| Файлы без расширения получают тип `"document"` и падают при отправке | Низкая | Среднее | `FSInputFile` + `answer_document` обрабатывает любые файлы; Telegram сам определяет формат |
| Изменение сигнатуры `_detect_slavik_media_type` (str|None → str) ломает неучтённых вызывателей | Низкая | Низкое | Функция приватная (`_`-префикс), используется только в `_pick_random_slavik_media()` — который тоже в этом же файле |
| GIF-детекция через `filepath.name` пропускает edge-case имена | Низкая | Среднее | Правила проверены на всех текущих именах файлов; идентичны CommonRelay (Epic 18 verified) |

---

### 28.8 Сводка файлов и изменений для Builder

| # | Файл | Что меняется | Сложность |
|---|------|-------------|-----------|
| **1** | `handlers/slavik.py` `_detect_slavik_media_type()` | Добавить `_AUDIO_EXTENSIONS`, `_VOICE_EXTENSIONS`; заменить `filepath.stem` на `filepath.name` с word-boundary; вернуть `"document"` вместо `None` | Низкая |
| **2** | `handlers/slavik.py` `_send_slavik_media()` | Добавить `elif` ветки для `"audio"`, `"voice"`, `"document"`; убрать `else` → `answer_photo` fallback | Низкая |
| **3** | `handlers/slavik.py` `_pick_random_slavik_media()` | Убрать фильтр `if media_type is not None`; добавить per-entry OSError try/except; улучшить INFO-лог | Низкая |

**Общая оценка сложности:** Низкая (3 функции, ~30 строк изменений, без новых файлов, без изменений конфигурации).

---

---

## 29. Epic 21 — MIMIC Propagation Fix + Time-Format Cooldowns

> **Версия:** v2.19.0
> **Дата:** 2026-08-03
> **Статус:** Архитектурный контракт. Дизайн Epic 21. Реализация НЕ начата.
> **Автор:** @Architect

### 29.1 Содержание Epic 21

| # | Задача | Суть |
|---|--------|------|
| **1** | T-149: MIMIC propagation fix | `alan_handler` не возвращает `UNHANDLED` → блокирует `common_router` (mimic, danger, otboy) |
| **2** | T-150–T-151: Time-format cooldowns | Новый хелпер `_parse_duration()`, переименование `*_COOLDOWN_SECONDS` → `*_COOLDOWN` |

### 29.2 Design Decision D49: return UNHANDLED in `alan_handler`

#### Проблема

`alan_handler` в `handlers/alan.py` ловит **все** сообщения от Alan (UserID 138811255) через `UserIdFilter`, но **не возвращает `UNHANDLED`**. В aiogram 3.x это означает «событие обработано» → propagation останавливается. Все нижестоящие роутеры (common_router, dead_page_router, war_alert_router) **не получают** сообщения Alan.

**Router position (из Приложения A):**
```
3. alan_router (UserIdFilter → Alan replies)
4. dead_page_router (F.forward_origin)
4b. war_alert_router (danger words, channel repost)
4c. common_router (mimic_handler, otboy_handler, danger_handler)  ← НЕДОСТУПЕН
5. slavik_router (Slavik catch-all)
```

**Последствия:** mimic_handler никогда не получает сообщения Alan → MIMIC фича сломана для единственного пользователя, под которого она настроена (`MIMIC_VICTIM_USER_IDS=138811255`).

Danger и otboy для Alan тоже не работают (но это expected — Alan обычно не пишет danger-слова).

**SLAVIK_MIMIC НЕ затронут** — он изолирован в `slavik_router` (позиция 5), который получает события независимо.

#### Root Cause

Файл `handlers/alan.py`:129 — последняя строка хэндлера:

```python
@alan_router.message(UserIdFilter(settings.ALAN_USER_ID))
async def alan_handler(message: types.Message) -> None:
    # ... counting, reply, silence greeting ...
    # NO return UNHANDLED — implicit None = "handled"
```

В aiogram 3.x конвенция:
- `return None` (или отсутствие return) = «событие обработано» → propagation stops
- `return UNHANDLED` = «событие НЕ обработано» → propagation continues to next routers
- `return False` (только для filters) = не матчит

#### Решение

```python
from aiogram.dispatcher.event.bases import UNHANDLED

@alan_router.message(UserIdFilter(settings.ALAN_USER_ID))
async def alan_handler(message: types.Message) -> None:
    # ... весь существующий код без изменений ...
    return UNHANDLED  # ← ЕДИНСТВЕННОЕ ИЗМЕНЕНИЕ
```

**Файл:** `handlers/alan.py`
**Сложность:** Минимальная (1 import + 1 return).
**Риски:** Нет. `alan_handler` только считает сообщения и иногда делает reply — он не должен блокировать propagation ни при каких условиях.

#### New Message Flow (after fix)

```
Alan пишет "привет как дела мир труд май"
  │
  ├─ alan_router (pos 3): count=1, не кратно 10, return UNHANDLED
  ├─ dead_page_router (pos 4): не forward → skip
  ├─ war_alert_router (pos 4b): не danger → skip
  ├─ common_router (pos 4c):
  │   ├─ mimic_handler: count_words=5 > 3 → MIMIC FIRES! ✅
  │   └─ danger/otboy: skip (нет ключевых слов)
  ├─ slavik_router (pos 5): не Slava → skip
  └─ vasya_router (pos 6): skip
```

### 29.3 Design Decision D50: Time-format cooldown system

#### Rationale

Текущие кулдауны — это `float` секунд в `.env`:
```
MIMIC_COOLDOWN_SECONDS=60.0
COMMON_COOLDOWN_SECONDS=0
DANGER_COOLDOWN_SECONDS=60.0
```

Недостатки:
1. **Нечитаемо**: `3600` — это час или просто много?
2. **Неудобно настраивать**: админ должен переводить часы/минуты в секунды.
3. **Нет валидации**: `3.14159` — не имеет смысла, но пройдёт.
4. **Несогласованный default для `DEAD_PAGE_COOLDOWN_SECONDS`**: int (10) вместо float.

#### Решение: `_parse_duration()` + `_env_duration()`

**Функция `_parse_duration(value: str) -> float`** (в `config/settings.py`):

| Формат ввода | Секунды | Пример |
|-------------|---------|--------|
| `"1s"` | `1.0` | 1 секунда |
| `"30s"` | `30.0` | 30 секунд |
| `"1m"` | `60.0` | 1 минута |
| `"5m"` | `300.0` | 5 минут |
| `"1h"` | `3600.0` | 1 час |
| `"2h"` | `7200.0` | 2 часа |
| `"1d"` | `86400.0` | 24 часа |
| `"0"` | `0.0` | Кулдаун отключён |
| `"0s"` | `0.0` | Кулдаун отключён |

**Правила валидации:**
- Строка должна состоять из цифр + опциональный суффикс `s`/`m`/`h`/`d`
- Число должно быть ≥ 0
- Пустая строка → `ValueError`
- Float-числа НЕ поддерживаются в duration-формате (`"0.5h"` → ошибка)
- Без суффикса → трактуется как количество секунд (`"60"` = 60.0)
- Неизвестный суффикс → `ValueError`
- Отрицательные числа → `ValueError`

**Функция `_env_duration(key: str, default: str) -> float`**:
- Читает значение из `os.getenv(key, default)`
- Вызывает `_parse_duration()` и возвращает float-секунды
- При ошибке парсинга → логирует WARNING и возвращает `_parse_duration(default)` как fallback

#### Полный список переименований

| Старое имя | Новое имя | Default | Был default |
|-----------|----------|---------|-------------|
| `MIMIC_COOLDOWN_SECONDS` | `MIMIC_COOLDOWN` | `"1h"` (3600s) | `60.0` |
| `SLAVIK_MIMIC_COOLDOWN_SECONDS` | `SLAVIK_MIMIC_COOLDOWN` | `"60s"` (60s) | `60.0` |
| `COMMON_COOLDOWN_SECONDS` | `COMMON_COOLDOWN` | `"0"` (disabled) | `0` |
| `DEAD_PAGE_COOLDOWN_SECONDS` | `DEAD_PAGE_COOLDOWN` | `"10s"` (10s) | `10` |
| `DANGER_COOLDOWN_SECONDS` | `DANGER_COOLDOWN` | `"60s"` (60s) | `60.0` |
| `OLYA_COOLDOWN_SECONDS` | `OLYA_COOLDOWN` | `"60s"` (60s) | `60.0` |

**SLAVIC_PHOTO_COOLDOWN** — не существует в текущем коде. Не добавляется.

#### Backward Compatibility

**Ломающее изменение**: старые float-значения в `.env` (`60.0`, `0`, `10`) **НЕ будут работать** с `_env_duration()`. Причина: `_parse_duration` проверяет суффиксы и отклонит чистый float. Админ **должен** обновить `.env` при деплое.

Переходный период: можно добавить fallback-логику в `_env_duration` — если значение похоже на число без суффикса и не содержит точку, трактовать как секунды. Но это временно, для обратной совместимости при деплое.

### 29.4 Affected Files Matrix

| # | Файл | Изменения | Сложность |
|---|------|-----------|-----------|
| **1** | `config/settings.py` | Добавить `_parse_duration()` + `_env_duration()`. Переименовать 6 полей `Settings`: `*_COOLDOWN_SECONDS` → `*_COOLDOWN`. Сменить тип c `_env_float`/`_env_int` на `_env_duration`. | **Средняя** |
| **2** | `handlers/alan.py` | Добавить `from aiogram.dispatcher.event.bases import UNHANDLED`. Добавить `return UNHANDLED` в конце `alan_handler()`. | **Низкая** |
| **3** | `bot.py` | Строки 80, 81, 88, 132, 137: переименовать `COOLDOWN_SECONDS` → `COOLDOWN`. | **Низкая** |
| **4** | `handlers/slavik.py` | Строка 122: `settings.SLAVIK_MIMIC_COOLDOWN_SECONDS` → `settings.SLAVIK_MIMIC_COOLDOWN`. | **Низкая** |
| **5** | `services/mimic_relay.py` | Конструктор `MimicRelay` принимает `cooldown_seconds` → не меняется (внутренний параметр). Но в `bot.py` при создании `MimicRelay` передаётся `settings.MIMIC_COOLDOWN`. | **Нет изменений** |
| **6** | `services/common_relay.py` | Конструктор `CommonRelay` принимает `cooldown_seconds` и `danger_cooldown_seconds` → не меняются (внутренние параметры). Но в `bot.py` передаются новые имена: `settings.COMMON_COOLDOWN` и `settings.DANGER_COOLDOWN`. | **Нет изменений** |
| **7** | `services/dead_page_relay.py` | Строка 78: `settings.DEAD_PAGE_COOLDOWN_SECONDS` → `settings.DEAD_PAGE_COOLDOWN`. Строка 82: аналогично в лог-сообщении. | **Низкая** |
| **8** | `.env.example` | Все 6 переменных переименованы. Defaults: `1h`, `60s`, `0`, `10s`, `60s`, `60s`. Добавлен комментарий про time-format. | **Низкая** |
| **9** | `README.md` | Обновить таблицу конфигурационных параметров (строки 86–149, 294, 475, 523). Заменить все `*_COOLDOWN_SECONDS` → `*_COOLDOWN` с time-format значениями. | **Средняя** |
| **10** | `tests/test_mimic_relay.py` | Тесты используют `cooldown_seconds` как параметр конструктора → **не меняется** (внутренний параметр). | **Нет изменений** |
| **11** | `tests/test_common.py` | Строка 973–975: `settings.COMMON_COOLDOWN_SECONDS` → `settings.COMMON_COOLDOWN`. Строка 400, 582, 756, 768 и др.: `cooldown_seconds` в `CommonRelay()` — **не меняется** (параметр конструктора). | **Низкая** |
| **12** | `tests/test_alan.py` | Добавить тест: `alan_handler` возвращает `UNHANDLED`. | **Низкая** |
| **13** | `tests/test_duration.py` | **Новый файл**: тесты `_parse_duration()` — все форматы, edge cases, ошибки. | **Средняя** |
| **14** | `plans/MEMORY.md` | Обновить таблицу конфигурационных параметров, список переменных `config/settings.py`. | **Низкая** |
| **15** | `plans/backlog.md` | Отметить T-149–T-158 как выполненные. | **Низкая** |

### 29.5 Integration Diagram: Message Flow After Fix

```
Сообщение от Alan (user_id=138811255)
    │
    ▼
┌─────────────────────────────────────────────────┐
│ admin_commands_router (pos 0)                   │  skip (not a command)
└─────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────┐
│ slava_presence_router (pos 1)                   │  skip (ChatMemberUpdated only)
│ alan_greeting_router (pos 1b)                   │  skip (ChatMemberUpdated only)
└─────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────┐
│ kostik_router (pos 2)                           │  skip (not Kostik)
└─────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────┐
│ alan_router (pos 3)                             │
│ ├─ UserIdFilter(ALAN_USER_ID) → matches        │
│ ├─ alan_handler(): count, maybe reply, ...      │
│ └─ return UNHANDLED  ← FIX                      │
└─────────────────────────────────────────────────┘
    │ propagation continues ▼
    ▼
┌─────────────────────────────────────────────────┐
│ dead_page_router (pos 4)                        │  skip (not forwarded from @d_pages)
└─────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────┐
│ war_alert_router (pos 4b)                       │  skip (no danger words in text)
└─────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────┐
│ common_router (pos 4c)                          │
│ ├─ mimic_handler: MIMIC FIRES! (if word_count  │
│ │   > MIMIC_MIN_WORDS + cooldown passed)       │
│ ├─ danger_handler: skip                         │
│ └─ otboy_handler: skip                          │
└─────────────────────────────────────────────────┘
    │ propagation continues ▼
    ▼
┌─────────────────────────────────────────────────┐
│ olya_router (pos 4d)                            │  skip (not Olya)
└─────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────┐
│ slavik_router (pos 5)                           │  skip (not Slava)
└─────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────┐
│ vasya_router (pos 6)                            │  skip (no matching text filters)
└─────────────────────────────────────────────────┘
```

### 29.6 `_parse_duration()` Specification

```python
def _parse_duration(value: str) -> float:
    """Convert a human-readable duration string to seconds (float).
    
    Formats: "<number>[s|m|h|d]"
      "1s"  = 1 second
      "30s" = 30 seconds  
      "1m"  = 60 seconds
      "1h"  = 3600 seconds
      "1d"  = 86400 seconds
      "0"   = 0 (disabled)
      "0s"  = 0 (disabled)
    
    Args:
        value: Duration string from env var.
    
    Returns:
        Float seconds.
    
    Raises:
        ValueError: If format is invalid, negative, or suffix is unknown.
    """
```

**Test cases for `test_duration.py`:**

| ID | Input | Expected | Notes |
|----|-------|----------|-------|
| D-01 | `"1s"` | `1.0` | Базовый |
| D-02 | `"30s"` | `30.0` | Много секунд |
| D-03 | `"1m"` | `60.0` | Минута |
| D-04 | `"5m"` | `300.0` | Много минут |
| D-05 | `"1h"` | `3600.0` | Час |
| D-06 | `"2h"` | `7200.0` | Два часа |
| D-07 | `"1d"` | `86400.0` | Сутки |
| D-08 | `"0"` | `0.0` | Zero без суффикса |
| D-09 | `"0s"` | `0.0` | Zero с суффиксом |
| D-10 | `"0m"` | `0.0` | Zero минут |
| D-11 | `"0h"` | `0.0` | Zero часов |
| D-12 | `""` | `ValueError` | Пустая строка |
| D-13 | `"1x"` | `ValueError` | Неизвестный суффикс |
| D-14 | `"-1s"` | `ValueError` | Отрицательное |
| D-15 | `"1.5h"` | `ValueError` | Float не поддерживается |
| D-16 | `"abc"` | `ValueError` | Не число |
| D-17 | `"60s"` | `60.0` | Секунды, равные минуте |
| D-18 | `"3600s"` | `3600.0` | Секунды, равные часу |

### 29.7 Риски

| Риск | Вероятность | Влияние | Митигация |
|------|-----------|---------|-----------|
| Старый `.env` на сервере с float-значениями сломает бота после деплоя | Высокая | **Критическое** | Добавить backward-compat fallback в `_env_duration` на переходный период: если чистое число (int), трактовать как секунды |
| `_parse_duration` падает на edge-case формате, который использует админ | Низкая | Среднее | Полное покрытие тестами (D-01–D-18) |
| Изменение `DEAD_PAGE_COOLDOWN_SECONDS` с int на float может сломать `was_dead_page_recently()` (DB ожидает int) | Средняя | Среднее | Проверить `DatabaseService.was_dead_page_recently()` — если ожидает int, привести к int в `dead_page_relay.py` при вызове |
| `return UNHANDLED` в `alan_handler` может вызвать двойное срабатывание F7v2 (silence greeting) если сообщение Alan дублируется через другие роутеры | Низкая | Низкое | `alan_handler` только считает сообщения и ставит timestamp — других side-effects нет |

### 29.8 Порядок реализации (для Builder)

1. **T-150**: Создать `_parse_duration()` и `_env_duration()` в `config/settings.py` (с backward-compat)
2. **T-151**: Переименовать все 6 полей в `Settings` + типы
3. **T-149**: Добавить `return UNHANDLED` в `handlers/alan.py`
4. **T-152**: Обновить `bot.py` — переименовать вызовы `settings.*_COOLDOWN_SECONDS` → `settings.*_COOLDOWN`
5. **T-153**: Обновить `handlers/slavik.py` — `SLAVIK_MIMIC_COOLDOWN_SECONDS` → `SLAVIK_MIMIC_COOLDOWN`
6. **T-154**: Обновить `services/dead_page_relay.py` — `DEAD_PAGE_COOLDOWN_SECONDS` → `DEAD_PAGE_COOLDOWN`
7. **T-157**: Обновить `.env.example`
8. **T-158**: Обновить тесты + создать `test_duration.py`
9. **T-159**: Прогнать все тесты
10. **T-160**: Обновить README.md
11. **T-161**: MEMORY.md + ARCHITECTURE.md sync
12. **T-162**: Commit + Push + Deploy

---

@Orchestrator Epic 21 architecture ready, passing the baton.

---

## 30. Epic 22 — Гонка функций и точность триггеров (v2.20.0)

> **Дата дизайна:** 2026-08-15 · **Автор:** @Architect · **Статус:** IMPLEMENTED ✅ — реализовано @Builder (D51–D54, T-163–T-167-C), стадия ревью
> **Цель:** устранить гонку ответов Славика (приветствие vs dead page vs «пошёл нахуй»),
> сделать триггеры точнее: Olya — только SaveAsBot-видео, mimic — не передразнивать
> репосты, PostPicker — не выбирать пост, отправленный в предыдущий раз.

### 30.1 PM-решения (из board.md) и их отображение на задачи

| PM | Задача | Суть решения |
|----|--------|--------------|
| D51 | T-163 | Логика ИЛИ сохраняется: caption-признак **ИЛИ** репост из `OLYA_SAVEASBOT_CHANNEL_IDS`. Дефолт `OLYA_ALWAYS_SEND` True→**False**. |
| D52 | T-164 | Единый параметр `MIMIC_FORWARDS_ENABLED: bool = False` для ОБОИХ mimic-механизмов (`handlers/common.py::mimic_handler` и `handlers/slavik.py::_slavik_mimic_should_trigger`). При `forward_origin is not None` и выключенном параметре — mimic пропускается. |
| D53 | T-165 | `DEAD_PAGE_POST_ON_JOIN=False` (join → только «ДОЛБОЕБ ВЕРНУЛСЯ»); dead_page_trigger — только репосты Славы (`UserIdFilter`, убрать is_present-гейт); catch-all Славика — гейт в начале: репост из @d_pages → `UNHANDLED` (dead page остаётся единственным ответом). Приветствие при входе в приоритете. |
| D54 | T-166 | Новый ключ `channel_state` `dead_page_last_sent:{chat_id}` (не путать с `last_known_message_id`). last_sent исключается из выбора (forward-scan, sequential, random ветки `services/dead_page_relay.py`); fallback на повтор при отсутствии альтернатив; запись msg_id после любого успешного форварда. Корень проблемы: при диапазоне ≤ 50 ID (`_SEQUENTIAL_THRESHOLD`) sequential scan всегда находит первый существующий пост (id 3). |
| — | T-167 | Документация (README/ARCHITECTURE/MEMORY, v2.20.0), полный pytest (0 регрессий, 586 + ~30 новых), коммит на русском (conventional commits). |

### 30.2 Контекст внешних API (дата 2026-08-15)

> Источники собраны с fallback-инструментом `exa_web_search_exa`: инструмент context7
> вернул «Invalid API key», DuckDuckGo — rate-limit («DDG detected an anomaly»). Все
> факты ниже перепроверены по официальной документации core.telegram.org и docs.aiogram.dev.

1. **`Message.forward_origin` в aiogram 3.x** — тип
   `MessageOriginUser | MessageOriginHiddenUser | MessageOriginChat | MessageOriginChannel | None`.
   **`None` — для обычных (не пересланных) сообщений.** Это основной детектор репоста:
   `message.forward_origin is not None`. Legacy-поля `forward_from`, `forward_from_chat`,
   `forward_from_message_id`, `forward_sender_name`, `forward_signature`, `forward_date`
   — **deprecated** (Bot API 7.0, 2023-12-29) и заменены на `forward_origin`.
   *Источники:* https://docs.aiogram.dev/en/dev-3.x/api/types/message.html (aiogram 3.27/3.28);
   https://core.telegram.org/bots/api-changelog (Bot API 7.0).
2. **`MessageOriginChannel`** — поля: `type` (`'channel'`), `date`, `chat: Chat` (канал, где
   сообщение было изначально отправлено), `message_id: int` (уникальный id сообщения внутри
   канала), `author_signature: str | None`. **Корректная детекция репоста из конкретного
   канала:** `isinstance(origin, MessageOriginChannel)` + сравнение `origin.chat.id` /
   `origin.chat.username` (паттерн уже реализован в `handlers/dead_page_trigger.py` и
   `handlers/war_alert.py`).
   *Источник:* https://docs.aiogram.dev/en/latest/api/types/message%5Forigin%5Fchannel.html
3. **4 типа MessageOrigin:** `MessageOriginUser` (`sender_user`), `MessageOriginHiddenUser`
   (`sender_user_name`), `MessageOriginChat` (`sender_chat`), `MessageOriginChannel` (`chat`).
   У всех есть `type` и `date`.
   *Источник:* https://core.telegram.org/bots/api#messageorigin
4. **`Message.caption: str | None`** — подпись для animation/audio/document/photo/video/voice.
   У пересланных медиа текст находится в `caption`, а не в `text`. Полный контент репоста:
   `message.text or message.caption` (паттерн уже в проекте: `DangerWordFilter`, `mimic_handler`).
   *Источники:* docs.aiogram.dev Message; community-практика (Latenode, SO) подтверждает:
   «For forwarded messages with photos, use message.caption instead of message.text».
5. **`forwardMessage`/`forwardMessages`:** «Use this method to forward messages of any kind.
   Service messages and messages with protected content can't be forwarded.» Бот должен быть
   членом (админом) канала-источника. Ошибка `Bad Request: message to forward not found` —
   штатный признак отсутствующего/удалённого пробного id → обрабатывать `continue`, не abort.
   `message_id` — сквозная нумерация в рамках чата (важно для sequential-scan).
   *Источники:* https://docs.aiogram.dev/en/latest/api/methods/forward_message.html;
   aiogram issue #1205; python-telegram-bot #1956; SO 66550987.
6. **Gotcha — origin на репостах:** `origin.chat` — это канал-ИСТОЧНИК, а пересылающего
   идентифицирует `message.from_user`. Пересланные альбомы не сохраняют общий
   `media_group_id` (группировать можно по `forward_origin.chat.id`).
   *Источники:* SO 79152213; aiogram discussion #1402.
7. **Gotcha — тесты (MagicMock):** атрибуты MagicMock автогенерируются и truthy —
   `message.forward_origin is not None` на MagicMock вернёт MagicMock (`True`). Тестовые
   фабрики (`conftest.make_message`, локальная `make_message` в `tests/test_common.py`)
   должны явно выставлять `msg.forward_origin = None`. Гейт в slavik catch-all сделан
   mock-safe через `isinstance(origin, MessageOriginChannel)`.
8. **Ограничения sendMediaGroup/forwardMessages:** альбом — 2–10 сообщений; `getChat`/
   `getChatMember` для каналов требуют членства бота (в проекте не используются — релей
   форвардит по id из канала, где бот — админ: `DEAD_PAGE_RELAY_CHANNEL_ID`).
   *Источник:* core.telegram.org/bots/api.

---

### 30.3 T-163 / D51 — Olya: реагировать только на SaveAsBot-видео

**Файлы и изменения (логика НЕ меняется — меняется только дефолт):**

| Файл | Изменение |
|------|-----------|
| `config/settings.py:204` | `OLYA_ALWAYS_SEND: bool = _env_bool("OLYA_ALWAYS_SEND", True)` → **`False`** |
| `.env.example:105` | `OLYA_ALWAYS_SEND=True` → **`OLYA_ALWAYS_SEND=False`** |
| `filters/olya_video.py` | **Без изменений.** ИЛИ-логика (строки 44–51) уже верна: `saveasbot_triggered = is_saveasbot or matched_caption`; `if saveasbot_triggered or always_send`. |
| `handlers/olya.py`, `services/olya_relay.py`, `bot.py` | Без изменений. |

**Итоговая матрица поведения (AC T-163-C):**

| Событие | ALWAYS_SEND=False (новый дефолт) | ALWAYS_SEND=True (явный override) |
|---------|----------------------------------|-----------------------------------|
| Обычное видео от Оли | `False` (не отвечаем) | `True` |
| Репост из SaveAsBot-канала (`OLYA_SAVEASBOT_CHANNEL_IDS`) | `True` | `True` |
| Caption содержит `OLYA_CAPTION_TEXT` | `True` | `True` |
| Caption **и** репост SaveAsBot | `True` | `True` |

**Псевдокод (текущий, подтверждённый — менять не нужно):**
```python
saveasbot_triggered = is_saveasbot or matched_caption
if saveasbot_triggered or settings.OLYA_ALWAYS_SEND:
    return {"is_saveasbot": saveasbot_triggered, "matched_caption": matched_caption}
return False
```

---

### 30.4 T-164 / D52 — Mimic: не передразнивать репосты

**Новый конфиг-параметр (один на оба механизма):**
- `config/settings.py`, секция «Mimic Feature» (после `MIMIC_COOLDOWN`, строка ~184):
  ```python
  # Мимикрировать только обычные сообщения; репосты пропускать.
  # True = передразнивать и репосты тоже.
  MIMIC_FORWARDS_ENABLED: bool = _env_bool("MIMIC_FORWARDS_ENABLED", False)
  ```
- `.env.example`, секция «Mimic Feature»:
  ```
  # Mimic только на обычные сообщения (не на репосты). True = включая репосты.
  MIMIC_FORWARDS_ENABLED=False
  ```

**Механизм 1 — `handlers/common.py::mimic_handler` (строки 144–177):**
```python
@common_router.message(UserIdFilter(*_MIMIC_USER_IDS))
async def mimic_handler(message: types.Message) -> None:
    if not _VICTIM_IDS:  # disabled
        return
    # ── D52: репосты не передразниваем (если не включено явно) ──
    if message.forward_origin is not None and not settings.MIMIC_FORWARDS_ENABLED:
        logger.debug(
            "Mimic: forwarded message — skipping (MIMIC_FORWARDS_ENABLED=False) | "
            "chat_id=%s | message_id=%s", message.chat.id, message.message_id,
        )
        return UNHANDLED
    if _mimic_relay is None:
        ...  # без изменений
    content = message.text or message.caption
    ...
    return UNHANDLED
```

**Механизм 2 — `handlers/slavik.py::_slavik_mimic_should_trigger` (строки 121–135):**
Сигнатура расширяется параметром с обратной совместимостью; гейт ставится ПЕРВЫМ:
```python
def _slavik_mimic_should_trigger(
    chat_id: int, text: str, is_forwarded: bool = False
) -> bool:
    """Check mimic conditions for Slavik: word count, cooldown, forward gate (D52)."""
    if is_forwarded and not settings.MIMIC_FORWARDS_ENABLED:
        return False          # D52: mimic пропускается → дальше Branch 3 «пошёл нахуй»
    if settings.SLAVIK_MIMIC_MIN_WORDS < 0:
        return False
    ...  # word count и cooldown без изменений
```
Call-site (Branch 2, строка 217):
```python
content = message.text or message.caption
if content and _slavik_mimic_should_trigger(
    message.chat.id, content,
    is_forwarded=message.forward_origin is not None,
):
```
**Семантика для Slavik:** при репосте и выключенном параметре mimic пропускается → фоллбэк
на Branch 3 («пошёл нахуй»), ЕСЛИ это не d_pages-репост (тогда сработает гейт Branch 0 из D53 —
см. 30.5.3, и сообщение останется без «пошёл нахуй»).

---

### 30.5 T-165 / D53 — Славик: приоритет приветствия, dead page только на репосты Славы из @d_pages

#### 30.5.1 Конфигурация

| Файл | Изменение |
|------|-----------|
| `config/settings.py:117` | `DEAD_PAGE_POST_ON_JOIN: bool = os.getenv("DEAD_PAGE_POST_ON_JOIN", "True").lower() in ("true", "1", "yes")` → **`_env_bool("DEAD_PAGE_POST_ON_JOIN", False)`** (заодно унифицируем с остальными bool-полями; `_env_bool` принимает `1/true/yes/on` — надмножество старого списка) |
| `.env.example:27` | `DEAD_PAGE_POST_ON_JOIN=True` → **`DEAD_PAGE_POST_ON_JOIN=False`** |
| `services/scheduler.py` | **Без изменений** — `SchedulerService.__init__` читает `settings.DEAD_PAGE_POST_ON_JOIN` при конструировании (строка 29); `signal_immediate_post` уже выходит по `if not self.post_on_join` (строки 46–48). |
| `handlers/slava_presence.py` | **Без изменений** — «ДОЛБОЕБ ВЕРНУЛСЯ» отправляется всегда; вызов `signal_immediate_post` остаётся (внутри него dead page теперь заглушен дефолтом). |

#### 30.5.2 `handlers/dead_page_trigger.py` — только репосты Славы

```python
from filters.user_id import UserIdFilter          # + import

@dead_page_router.message(
    F.forward_origin,
    UserIdFilter(settings.SLAVIK_USER_ID),        # ← D53: только репосты Славы
)
async def on_forward(message: types.Message):
    origin = message.forward_origin
    if not isinstance(origin, MessageOriginChannel):
        logger.debug(...)
        return UNHANDLED                          # без изменений
    ...  # определение is_target (username/id) без изменений
    if not is_target:
        return UNHANDLED                          # без изменений
    ...  # media-group dedup (Epic 14) — БЕЗ изменений

    # ── D53: is_present-гейт УДАЛЯЕТСЯ (строки 82–87) ──
    # Репост Славы сам по себе означает, что Слава в чате.
    # _db остаётся в сигнатуре setup_dead_page(relay, db) для совместимости с bot.py:72,
    # но больше не используется в этом модуле.

    if _relay is None:
        logger.error("DeadPageRelay not initialized — cannot send dead page")
        return                                    # implicit None → propagation stop (как сейчас)
    await _relay.send_dead_page(chat_id, slot="repost")
    # implicit None в конце — намеренно: d_pages-репост Славы ОСТАНАВЛИВАЕТ propagation,
    # dead page остаётся единственным ответом (существующее поведение, сохраняем).
```

Ключевой момент: не-Славины репосты теперь отсекаются **фильтром** (handler не вызывается →
propagation продолжается, в отличие от прежнего `return`-паттерна). Это чинит старый класс
багов (см. секцию 1.2) и для d_pages-репостов других пользователей.

#### 30.5.3 Catch-all гейт в `handlers/slavik.py`

```python
from aiogram.dispatcher.event.bases import UNHANDLED       # + import
from aiogram.types import MessageOriginChannel             # + import

@slavik_router.message(UserIdFilter(settings.SLAVIK_USER_ID))
async def slavik_catchall_handler(message: types.Message):
    logger.debug(...)

    # ── Branch 0: Dead Page gate (Epic 22 / D53) ──
    # d_pages-репост принадлежит dead_page_router (позиция 4). Defense-in-depth:
    # если событие всё же дошло сюда — уступить, dead page должен быть ЕДИНСТВЕННЫМ ответом.
    origin = message.forward_origin
    if isinstance(origin, MessageOriginChannel):
        src_username = settings.DEAD_PAGE_SOURCE_CHANNEL_USERNAME
        src_id = settings.DEAD_PAGE_SOURCE_CHANNEL_ID
        if (src_username and origin.chat.username == src_username) or (
            src_id and origin.chat.id == src_id
        ):
            logger.info(
                "Slavik catchall: d_pages repost — yielding to dead_page_router | msg_id=%d",
                message.message_id,
            )
            return UNHANDLED    # ни photo, ни mimic, ни «пошёл нахуй»

    # Branch 1 (photo interval), Branch 2 (mimic c is_forwarded), Branch 3 («пошёл нахуй») — без изменений
```

#### 30.5.4 Приоритеты и propagation — точная последовательность

Целевая иерархия: **«приветствие при входе» > «dead page» > (нет ответа) > «пошёл нахуй»**.

1. **Join-событие:** `slava_presence_router` (позиция 1) отправляет только
   «ДОЛБОЕБ ВЕРНУЛСЯ»; `signal_immediate_post` выходит по дефолту (`DEAD_PAGE_POST_ON_JOIN=False`).
   ChatMemberUpdated-события вообще не пересекаются с message-роутерами → гонки нет.
2. **d_pages-репост Славы:** матчится `dead_page_router` (позиция 4) → `send_dead_page` →
   implicit `None` в конце handler'а **останавливает propagation** → `slavik_router` (позиция 5)
   событие не получает → ни photo, ни mimic, ни «пошёл нахуй». Dead page — единственный ответ.
3. **Defense-in-depth:** если событие всё же достигает catch-all (другая версия aiogram/
   прямой вызов хендлера в тестах) — гейт Branch 0 возвращает `UNHANDLED`.
4. **Не-d_pages репост Славы:** trigger возвращает `UNHANDLED` → propagation идёт дальше →
   mimic пропускается (D52, Branch 2) → Branch 3 «пошёл нахуй».
5. **Обычное сообщение Славы:** без изменений — Branch 1 (photo interval) > Branch 2 (mimic) >
   Branch 3 («пошёл нахуй»).

#### 30.5.5 Почему порядок роутеров НЕ меняется

- `dead_page_router` (4) уже стоит ДО `slavik_router` (5) — это и даёт приоритет dead page.
  Перенос позиций ничего не добавил бы.
- `war_alert_router` (4b) и `common_router` (4c) между ними не матчат d_pages-репосты в
  общем случае; danger-ответ на d_pages-репост с danger-словами — существующее поведение,
  вне скоупа (board, риск 3): propagation останавливается на dead_page handler'е.
- Всё необходимое достигается сужением ФИЛЬТРОВ (UserIdFilter + гейт), а не перестановкой
  роутеров — минимальный риск для остальных 20+ фич.

---

### 30.6 T-166 / D54 — PostPicker: не выбирать пост, отправленный в прошлый раз

#### 30.6.1 Схема данных

Новых таблиц нет — используем существующую `channel_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)`.

| Ключ | Тип значения | Смысл | Кто пишет/читает |
|------|--------------|-------|------------------|
| `dead_page_last_sent:{chat_id}` | `str(int)` — message_id первичного поста релей-канала | Анти-повтор: пост, отправленный в этот чат в прошлый раз | `DatabaseService.get/set_dead_page_last_sent`; `DeadPageRelay` |
| `last_known_message_id` / `last_msg_id:{channel_id}` | `str(int)` | **НЕ ПУТАТЬ:** глобальная верхняя граница для forward-scan (существующее) | без изменений |
| `alan_last_msg:{chat_id}`, `slavic_photo:{chat_id}` | — | существующие паттерны key-per-chat | — |

#### 30.6.2 `services/database.py` — новые методы (после `update_last_known_message_id`, ~строка 193)

```python
async def get_dead_page_last_sent(self, chat_id: int) -> int | None:
    """Primary relay-channel msg_id forwarded into this chat last time (anti-repeat)."""
    key = f"dead_page_last_sent:{chat_id}"
    cursor = await self.db.execute("SELECT value FROM channel_state WHERE key = ?", (key,))
    row = await cursor.fetchone()
    if row:
        try:
            return int(row["value"])
        except (ValueError, TypeError):
            return None
    return None

async def set_dead_page_last_sent(self, chat_id: int, msg_id: int) -> None:
    key = f"dead_page_last_sent:{chat_id}"
    await self.db.execute(
        "INSERT OR REPLACE INTO channel_state (key, value) VALUES (?, ?)",
        (key, str(msg_id)),
    )
    await self.db.commit()
```

#### 30.6.3 `services/dead_page_relay.py` — псевдокод

```python
# ── send_dead_page (строка 70) ──
async def send_dead_page(self, chat_id: int, slot: str = "repost") -> None:
    ...  # cooldown-проверка без изменений

    try:
        last_sent = await self.db.get_dead_page_last_sent(chat_id)
    except Exception:
        logger.warning("[dead_page] get_dead_page_last_sent failed — anti-repeat disabled", exc_info=True)
        last_sent = None

    success_msg_id = await self._try_forward_from_channel(chat_id, last_sent)

    if success_msg_id is None:
        logger.warning("[dead_page] FALLBACK: channel forward failed ...")
        await self._fallback_local_send(chat_id)
    else:
        try:
            await self.db.set_dead_page_last_sent(chat_id, success_msg_id)  # ← D54: запись после успеха
        except Exception:
            logger.warning("[dead_page] set_dead_page_last_sent failed", exc_info=True)

    await self.db.record_dead_page_post(chat_id, slot)
    ...

# ── _try_forward_from_channel (строка 100) — КОНТРАКТ МЕНЯЕТСЯ: bool → int | None ──
async def _try_forward_from_channel(self, chat_id: int, last_sent: int | None = None) -> int | None:
    """Returns the primary relay-channel msg_id that was forwarded, or None."""
    ...
    # Forward scan (строки 121–146): пропускать last_sent
    if last_msg_id and last_msg_id > 0:
        for probe_id in range(last_msg_id + 1, last_msg_id + _FORWARD_SCAN_LIMIT + 1):
            if last_sent is not None and probe_id == last_sent:
                continue                      # ← D54: skip, попытку не тратим
            try:
                result = await self._forward_single(chat_id, probe_id, last_msg_id)
                ...
                return probe_id               # было: return result
            except Exception as e: ...        # без изменений

    for range_idx, (lo, hi) in enumerate(ranges):
        if range_size <= _SEQUENTIAL_THRESHOLD:
            # Sequential scan (строки 159–188): пропускать last_sent
            for msg_id in range(lo, hi + 1):
                if last_sent is not None and msg_id == last_sent:
                    continue                  # ← D54: решает «всегда id 3» (первый существующий)
                try:
                    result = await self._forward_with_album_detection(chat_id, msg_id, last_msg_id)
                    ...
                    return msg_id             # было: return result
                except Exception as e: ...    # без изменений
        else:
            # Random probing (строки 190–233): re-roll last_sent БЕЗ сжигания attempt
            tried, attempts, re_rolls = set(), 0, 0
            while attempts < self.max_retries:
                msg_id = random.randint(lo, hi)
                if msg_id in tried:
                    continue
                if last_sent is not None and msg_id == last_sent:
                    re_rolls += 1
                    if re_rolls <= 20:
                        continue              # ← D54: re-roll без attempt (bounded — защита от бесконечного цикла)
                    break                     # диапазон «состоит только из last_sent» → сдаёмся
                tried.add(msg_id)
                attempts += 1
                ...
                return msg_id                 # было: return result

    # ← D54: last-resort fallback — повтор при отсутствии альтернатив (после ВСЕХ диапазонов)
    if last_sent is not None:
        logger.warning("[dead_page] No alternative posts — repeating last sent msg_id=%d", last_sent)
        try:
            if await self._forward_with_album_detection(chat_id, last_sent, last_msg_id):
                return last_sent
        except Exception as e:
            logger.error("[dead_page] Last-sent fallback failed: msg_id=%d → %s", last_sent, e, exc_info=True)

    logger.error(... ALL RANGES EXHAUSTED ...)
    return None                                # было: return False
```

**Не меняются:** `_forward_single`, `_forward_album_post_send`, `_forward_with_album_detection`,
`_forward_with_heuristic` (остаются `-> bool`; кандидат известен на call-site). Обновление
`update_last_known_message_id` — без изменений (отвечает за верхнюю границу скана).

**Запись last_sent:** только при успешном канальном форварде, всегда **primary id**
(кандидат, инициировавший форвард) — в т.ч. для альбомов (записывается id первичного поста,
а не max). Fallback на локальные медиа (`_fallback_local_send`) last_sent **не** записывает
(нет message_id). Ручной `/deadpage` проходит тот же путь и тоже записывает — корректно.

#### 30.6.4 Edge cases (T-166)

| Кейс | Поведение |
|------|-----------|
| Ключа в БД нет (первый запуск) | `last_sent=None` → поведение идентично текущему |
| Канал: один пост (id 3), last_sent=3 | все ветки пропускают 3 → last-resort fallback → повтор 3 (осознанный повтор, PM D54) |
| Канал: посты 3 и 4, last_sent=3 | sequential [1,10] пропускает 3, находит 4 → форвард 4 |
| Random: randint вернул last_sent | re-roll без сжигания attempt (≤ 20 re-rolls) |
| Альбом: primary записан; следующий выбор попал в sibling | повтор части альбома возможен (низкая вероятность, принято) |
| Ошибка БД на get/set | graceful degrade: anti-repeat отключается, dead page работает |
| Multi-chat | ключ per-`{chat_id}` — изоляция чатов |

---

### 30.7 Конфигурационные изменения — сводная таблица

| Поле | Где (settings.py) | Было | Стало | .env.example |
|------|-------------------|------|-------|--------------|
| `OLYA_ALWAYS_SEND` | строка 204 | `_env_bool(..., True)` | `_env_bool(..., False)` | `OLYA_ALWAYS_SEND=False` |
| `MIMIC_FORWARDS_ENABLED` | НОВОЕ, секция Mimic (~184) | — | `_env_bool("MIMIC_FORWARDS_ENABLED", False)` | `MIMIC_FORWARDS_ENABLED=False` |
| `DEAD_PAGE_POST_ON_JOIN` | строка 117 | `os.getenv(..., "True").lower() in ("true","1","yes")` | `_env_bool("DEAD_PAGE_POST_ON_JOIN", False)` | `DEAD_PAGE_POST_ON_JOIN=False` |

---

### 30.8 Тестовый план

**Новые тесты (~30):**

| Файл | Кейсы |
|------|-------|
| `tests/test_olya.py` (~3) | дефолт без override → обычное видео `False`; ALWAYS_SEND=True → `True` (существующий); ИЛИ-матрица caption+repost (существующие + проверка дефолта) |
| `tests/test_common.py` (~4, класс `TestMimicForwardsGate`) | mimic_handler: forwarded+off → `UNHANDLED` и `send_mimic` не вызван; forwarded+on → вызван; обычное сообщение+off → вызван; forwarded без content → skip |
| `tests/test_slavik_handlers.py` (~5) | `_slavik_mimic_should_trigger(is_forwarded=...)` матрица 2×2; catchall: d_pages-репост → `UNHANDLED` и ноль ответов; репост другого канала → «пошёл нахуй»; обычное сообщение — без регрессий |
| `tests/test_dead_page_trigger.py` (переработка + ~3 новых) | Slava-репост @d_pages → relay вызван (user id = `SLAVIK_USER_ID`); не-Славин репост → фильтр `False` (UserIdFilter) и relay не вызван; `db.is_present` больше НЕ вызывается; остальные каналы → `UNHANDLED`; dedup-кейсы (обновить user id) |
| `tests/test_slavik_priority.py` (НОВЫЙ, ~3, интеграционные через `Dispatcher`) | join → ровно 1 ответ «ДОЛБОЕБ ВЕРНУЛСЯ» и relay НЕ вызван; d_pages-репост через Dispatcher (dead_page_router + slavik_router) → ровно 1 dead page, нет «пошёл нахуй»/mimic; cooldown активен → всё равно нет «пошёл нахуй» (гейт держит) |
| `tests/test_database.py` (+3) | `get/set_dead_page_last_sent` roundtrip; per-chat изоляция (A=3, B=7); отсутствие ключа → `None`; битое значение → `None` |
| `tests/test_dead_page_relay.py` (+9) | sequential пропускает last_sent → следующий существующий; forward-scan пропускает; random re-rolls last_sent без attempt (mock `random.randint`: 7,7,last_sent,5 → attempts=2); last-resort повтор при единственном посте; запись last_sent после успеха; запись primary id для альбома; fallback local → last_sent НЕ пишется; ошибка БД на get → graceful; `last_sent=None` → поведение как сегодня |
| `tests/test_scheduler.py` (+1) | дефолтный `SchedulerService` (без override) с `DEAD_PAGE_POST_ON_JOIN=False` → `signal_immediate_post` пропускает |

**Затронутые существующие тесты (обязательная адаптация):**

| Файл | Что затронуто |
|------|---------------|
| `tests/test_dead_page_relay.py` | 9 строк: `assert result is True/False` → `assert result == <msg_id>` / `assert result is None` (строки 342, 390, 429, 462, 486, 530, 582, 610, 636); прямые вызовы `_try_forward_from_channel` совместимы (новый параметр с дефолтом `None`) |
| `tests/test_dead_page_trigger.py` | все 8 тестов: user id в `make_forward_message` → `SLAVIK_USER_ID`; фикстура `mock_db.is_present` и кейс `test_skips_when_slava_not_present` удаляются (гейт снят) |
| `tests/conftest.py` + `tests/test_common.py` (локальная фабрика) | добавить `msg.forward_origin = None` в `make_message` (MagicMock-готовность, см. 30.2 п.7) |
| `tests/test_olya.py` | ревью: хелпер `_modified_settings` уже параметризует `OLYA_ALWAYS_SEND` явно — точечные правки при необходимости |
| `tests/test_slavik_handlers.py` | гейт Branch 0 mock-safe (`isinstance`), фабрики дополняются `forward_origin=None` — правки минимальны |
| `tests/test_scheduler.py`, `tests/test_slava_presence.py` | без изменений (+1 новый кейс в scheduler) |

**Итого:** 586 существующих + ~30 новых ≈ **616 тестов**, 0 регрессий.

---

### 30.9 Риски миграции

| # | Риск | Митигация |
|---|------|-----------|
| R1 | **Prod `.env` может содержать явные `OLYA_ALWAYS_SEND=True` / `DEAD_PAGE_POST_ON_JOIN=True`** — дефолты не применятся, старое поведение молча останется | Деплой-чеклист: поправить/удалить эти строки в prod `.env` (board-риск 1); smoke-тесты после рестарта |
| R2 | Контракт `_try_forward_from_channel: bool → int \| None` | Единственный production-вызывающий — `send_dead_page`; в тестах 9 assertion-строк обновляются в рамках T-166 |
| R3 | 586 существующих тестов | Полный прогон в T-167; адаптации перечислены в 30.8; новые фабрики выставляют `forward_origin=None` |
| R4 | Бесконечный re-roll в random probing (диапазон = {last_sent}) | Bounded re-rolls ≤ 20 → `break`; last-resort fallback выполняется после ВСЕХ диапазонов |
| R5 | Sequential scan «всегда id 3» | Исправляется skip'ом last_sent; при единственном посте — осознанный повтор (требование D54) |
| R6 | Альбомы: primary записан, sibling может повториться | Принято (вероятность низкая); запись именно primary id зафиксирована в 30.6.3 |
| R7 | Миграция БД | Не нужна: переиспользуется `channel_state` (без ALTER/CREATE) |
| R8 | Danger-ответ на d_pages-репост | Существующее поведение (propagation останавливается на dead_page), вне скоупа Epic 22 (board-риск 3) |
| R9 | MagicMock truthy-атрибуты в тестах | Гейты пишутся mock-safe (`isinstance`); фабрики дополняются `forward_origin=None` |
| R10 | Версия | v2.19.0 → **v2.20.0**: README changelog, MEMORY.md, header ARCHITECTURE.md |

---

### 30.10 Сводка для Builder — точные сигнатуры изменений

1. `config/settings.py`
   - `OLYA_ALWAYS_SEND: bool = _env_bool("OLYA_ALWAYS_SEND", False)`  (строка 204, дефолт True→False)
   - `MIMIC_FORWARDS_ENABLED: bool = _env_bool("MIMIC_FORWARDS_ENABLED", False)`  (НОВОЕ)
   - `DEAD_PAGE_POST_ON_JOIN: bool = _env_bool("DEAD_PAGE_POST_ON_JOIN", False)`  (строка 117, замена os.getenv-выражения)
2. `.env.example` — 3 правки (30.7).
3. `handlers/common.py::mimic_handler` — гейт после `if not _VICTIM_IDS`:
   `if message.forward_origin is not None and not settings.MIMIC_FORWARDS_ENABLED: return UNHANDLED`.
4. `handlers/slavik.py`
   - imports: `UNHANDLED`, `MessageOriginChannel`;
   - `_slavik_mimic_should_trigger(chat_id: int, text: str, is_forwarded: bool = False) -> bool` — гейт первой строкой;
   - `slavik_catchall_handler`: Branch 0 (d_pages-гейт) в начале; Branch 2 вызывает mimic с `is_forwarded=message.forward_origin is not None`.
5. `handlers/dead_page_trigger.py`
   - `@dead_page_router.message(F.forward_origin, UserIdFilter(settings.SLAVIK_USER_ID))`;
   - удалить is_present-блок (строки 82–87); `setup_dead_page(relay, db)` — сигнатуру сохранить.
6. `services/database.py` — `get_dead_page_last_sent(chat_id) -> int | None`, `set_dead_page_last_sent(chat_id, msg_id) -> None` (ключ `dead_page_last_sent:{chat_id}`).
7. `services/dead_page_relay.py`
   - `send_dead_page`: загрузка last_sent → `_try_forward_from_channel(chat_id, last_sent)` → запись last_sent при успехе;
   - `_try_forward_from_channel(self, chat_id: int, last_sent: int | None = None) -> int | None` — skip в forward-scan/sequential, bounded re-roll в random, last-resort fallback после всех диапазонов, `return None` вместо `False`.
8. **НЕ менять:** `bot.py` (порядок роутеров, setup-вызовы), `services/scheduler.py`, `filters/olya_video.py`, `handlers/olya.py`, `handlers/slava_presence.py`, `services/olya_relay.py`.

### 30.11 Порядок реализации

1. **T-163** (config + тесты) → 2. **T-164** (config + 2 mimic-механизма + тесты) →
3. **T-165** (config + trigger + catch-all гейт + интеграционные тесты) →
4. **T-166** (DB-методы + relay + тесты) → 5. **T-167** (README/MEMORY/ARCHITECTURE sync v2.20.0,
   полный pytest ≈ 616 тестов, коммит на русском `feat: ...` / `fix: ...`, push; деплой — DevOps).

---

@Orchestrator Epic 22 (T-163..T-167) architecture ready — v2.20.0 design passed to @Builder.

---

## 31. Конвенция media/ (2026-08-16)

> **Дата:** 2026-08-16
> **Статус:** Конвенция (обязательна к исполнению). По указанию пользователя.

### 31.1 Конвенция

Конвенция media/ (по указанию пользователя, 2026-08-16): все изменения в папке `media/` — **сознательные**, делаются для загрузки на сервер и использования ботом; media-файлы:
- **не являются артефактами** — не исключаются из коммитов;
- **не добавляются в `.gitignore`**;
- **не удаляются** без явного указания пользователя.

**Пример:** `danger_drone.mp4` — 16-й файл danger-пула (`media/common/danger/`), добавлен намеренно; `media_picker` подхватывает файлы автоматически (без правок кода).

**Chore-задача (2026-08-16):** закоммитить и задеплоить `media/common/danger/danger_drone.mp4`.

### 31.2 Инвентарь медиа-пулов

| Пул | Директория | Файлов | Примечание |
|-----|-----------|--------|------------|
| danger | `media/common/danger/` | **16** | `danger_drone.mp4` — 16-й файл (2026-08-16, добавлен намеренно) |
| otboy | `media/common/otboy/` | 1 | `otboy_01.jpg` |
| olya cringe | `media/olya/cringe/` | 2 | `olya_cringe_01.mp4`, `olya_cringe_02.mp4` |
| slavik random | `media/slavik/slavik_random/` | 5 | photo + video/animation mix |

---

## 32. Epic 23 — Точная настройка danger-словаря (v2.21.0)

> **Дата:** 2026-08-16
> **Статус:** DONE & DEPLOYED ✅ — T-169..T-172 DONE (672 теста PASS, ревью 2 раунда). Деплой: git pull 0c74220..756d237 (9 файлов), systemctl active (running) PID 917681, .env DANGER_WORDS пустой (дефолты), проверка «118 17» совпала, логи чистые. Прод v2.21.0.
> **Цель:** убрать ложноположительные секции danger-словаря, ввести механику фраз, добавить журналистские синонимы взрыва.

### 32.1 PM-решения D55–D58 и отображение на задачи

| # | Решение | Задачи |
|---|---------|--------|
| **D55** | `DANGER_PHRASES: list[str]` в `filters/word_lists.py` + ветка фраз в `DangerWordFilter` (regex `(?<![а-яё]){фраза}(?![а-яё])`, IGNORECASE, возврат `{"matched_word": <фраза в регистре текста>}`). Env-оверрайда фраз НЕТ — фразы всегда из дефолтов | T-171 |
| **D56** | Shelter: удалить 26 одиночных форм, добавить 10 фраз | T-169 |
| **D57** | Flash: `вспышка*`/`взрыв*` остаются; + одиночные `хлопок`, `хлопки`, `хлопнуло`, `хлопнул` (омоним-риск принят) | T-169 |
| **D58** | Атака: удалить 28 одиночных форм, добавить 7 фраз | T-170 |
| Доп. | Удалить секции Flight/arrival и Падение/сбитие полностью | T-169 |

### 32.2 Итоговое содержимое `filters/word_lists.py`

**Точный подсчёт из реального кода (2026-08-16):** текущий `DANGER_WORDS` = **191** словоформа (README говорит «187» — рассинхрон на 4, зафиксирован в 32.3). Удаляются: Flight 10 + Shelter 26 + Атака/угроза 28 + Падение/сбитие 13 = **77**. Добавляются 4 (хлопки). **Итог: 118 словоформ.**

```python
"""Shared danger word lists — DANGER_WORDS + DANGER_PHRASES.

DANGER_WORDS: flat list of lowercase single-word forms.
DANGER_PHRASES: flat list of lowercase multi-word phrases (Epic 23).
Used by DangerWordFilter (words + phrases) — единый источник для
war_alert (4b) и common/danger (4c).
"""

DANGER_WORDS: list[str] = [
    # ── Drone / UAV ──
    'дрон', 'дроны', 'дронов', 'дрону', 'дроном', 'дроне',
    'дронам', 'дронами', 'дронах',
    'беспилотник', 'беспилотники', 'беспилотника', 'беспилотнику',
    'беспилотником', 'беспилотнике', 'беспилотников', 'беспилотникам',
    'беспилотниками', 'беспилотниках',
    'бпла',
    # ── Shahed drones ──
    'шахед', 'шахеды',
    # ── Rocket / missile ──
    'ракета', 'ракеты', 'ракет', 'ракете', 'ракету', 'ракетой',
    'ракетою', 'ракетам', 'ракетами', 'ракетах',
    'ракетная', 'ракетной', 'ракетную', 'ракетною',
    'ракетные', 'ракетных', 'ракетным', 'ракетными',
    'ракетный', 'ракетного', 'ракетному',
    'баллистическая', 'крылатая',
    # ── Flash / explosion ──
    'вспышка', 'вспышки', 'вспышке', 'вспышку', 'вспышкой',
    'вспышек', 'вспышкам', 'вспышками', 'вспышках',
    'взрыв', 'взрыва', 'взрыву', 'взрывом', 'взрыве',
    'взрывы', 'взрывов', 'взрывам', 'взрывами', 'взрывах',
    'хлопок', 'хлопки', 'хлопнуло', 'хлопнул',  # D57 (NEW)
    # ── Danger / alert ──
    'опасность', 'опасности', 'опасностью', 'опасностей',
    'опасен', 'опасна', 'опасно', 'опасны',
    'тревога', 'тревоги', 'тревоге', 'тревогу', 'тревогой',
    'внимание',
    'оповещение', 'оповещения', 'оповещению', 'оповещением',
    'оповещении', 'оповещений',
    # ── Сирена / воздушная тревога ──
    'сирена', 'сирены', 'сирену', 'сиреной', 'сирене',
    'сирен', 'сиренам', 'сиренами', 'сиренах',
    'воздушная', 'воздушной', 'воздушную',
    # ── Беспилотные (adjectives) ──
    'беспилотной', 'беспилотная', 'беспилотное', 'беспилотные',
    'беспилотного', 'беспилотному', 'беспилотным',
    'беспилотных',
    # ── Эвакуация ──
    'эвакуация', 'эвакуации', 'эвакуацию', 'эвакуацией',
    'эвакуироваться',
    # ── Отбой ──
    'отбой', 'отбоя', 'отбою', 'отбоем', 'отбое',
]

DANGER_PHRASES: list[str] = [
    # ── Shelter phrases (D56) — longest-first ordering (см. 32.6 п.6) ──
    'укрыться в убежище',
    'уйти в бомбоубежище',
    'пройти в убежище',
    'спрятаться в бункере',
    'бегом в укрытие',
    'иди в бункер',
    'в бомбоубежище',
    'в убежище',
    'в укрытие',
    'в бункер',
    # ── Attack phrases (D58) ──
    'беспилотная атака',
    'ракетная атака',
    'атака дронов',
    'атака беспилотников',
    'ракетный обстрел',
    'артиллерийский обстрел',
    'массированный обстрел',
]
```

Контроль (AC T-169-G / T-170-C): `DANGER_WORDS` остаётся плоским `list[str]` lowercase с секциями-комментариями; ни одной формы `летит/прилет/укрыт*/убежищ*/бункер*/атак*/угроз*/обстрел*/сбит*/упал*/падени*` в `DANGER_WORDS` не остаётся; `хлопок/хлопки/хлопнуло/хлопнул` присутствуют.

### 32.3 Подсчёт словоформ (для README-sync)

| Секция | Было | Стало |
|--------|------|-------|
| Flight/arrival | 10 | **0** (удалена) |
| Drone/UAV | 20 | 20 |
| Shahed | 2 | 2 |
| Rocket/missile | 23 | 23 |
| Shelter/bunker | 26 | **0** (→ 10 фраз) |
| Flash/explosion | 19 | **23** (+4 хлопка) |
| Danger/alert | 20 | 20 |
| Сирена + воздушная* | 12 | 12 |
| Беспилотные (прилаг.) | 8 | 8 |
| Атака/угроза/обстрел | 28 | **0** (→ 7 фраз) |
| Падение/сбитие | 13 | **0** (удалена) |
| Эвакуация | 5 | 5 |
| Отбой | 5 | 5 |
| **Итого слов** | **191** | **118** |
| **Фразы** | — | **17** (10 shelter + 7 attack) |
| **Всего паттернов** | 191 | **135** |

⚠️ **Рассинхрон с PM-оценкой:** backlog T-172-A оценивал «119 словоформ»; фактический подсчёт из кода — **118** (191 − 77 + 4). Принято фактическое число 118, задача T-172-A скорректирована. README ранее писал «187» при фактических 191 — историческая неточность; в v2.21.0 указываем точные числа.

### 32.4 Механика `DangerWordFilter` (filters/danger_word.py)

**Было:** один цикл по `self._patterns` (слова). **Стало:** две ветки — фразы, затем слова.

Точные сигнатуры:

```python
def _build_danger_patterns(words: list[str]) -> list[re.Pattern]: ...  # БЕЗ изменений

def _build_phrase_patterns(phrases: list[str]) -> list[re.Pattern]:
    """Compile regex patterns for multi-word phrases (D55).

    Same boundary logic as _build_danger_patterns, applied to the whole
    phrase: (?<![а-яё]){phrase}(?![а-яё]) — spaces inside the phrase are
    literal (re.escape), boundaries only at the phrase edges.
    """
    patterns: list[re.Pattern] = []
    for phrase in phrases:
        try:
            patterns.append(
                re.compile(
                    rf"(?<![а-яё]){re.escape(phrase)}(?![а-яё])",
                    re.IGNORECASE,
                )
            )
        except re.error:
            logger.warning(
                "DangerWordFilter: failed to compile pattern for phrase %r", phrase
            )
    return patterns

def _parse_danger_words(raw: str) -> list[str]: ...  # БЕЗ изменений

class DangerWordFilter(BaseFilter):
    def __init__(self, words: list[str] | None = None) -> None:
        if words is not None:
            self._words = words
        else:
            self._words = _parse_danger_words(settings.DANGER_WORDS)
        self._patterns = _build_danger_patterns(self._words)
        # D55: фразы ВСЕГДА из дефолтов word_lists.py — env-оверрайда нет
        self._phrase_patterns = _build_phrase_patterns(DANGER_PHRASES)

    async def __call__(self, message: Message) -> dict[str, str] | bool:
        content = message.text or message.caption
        if not content or not isinstance(content, str):
            return False

        # 1) Ветка фраз ПЕРВАЯ (обоснование — 32.5)
        for p in self._phrase_patterns:
            match = p.search(content)
            if match:
                matched_phrase = match.group()
                logger.info(
                    "DangerWordFilter matched phrase | phrase=%r | msg_id=%s | chat_id=%s",
                    matched_phrase, message.message_id, message.chat.id,
                )
                return {"matched_word": matched_phrase}

        # 2) Ветка одиночных слов (как раньше)
        for p in self._patterns:
            match = p.search(content)
            if match:
                matched_word = match.group()
                logger.info(
                    "DangerWordFilter matched | word=%r | msg_id=%s | chat_id=%s",
                    matched_word, message.message_id, message.chat.id,
                )
                return {"matched_word": matched_word}
        return False
```

**Обратная совместимость:** возврат остаётся `dict` с ключом **`matched_word`** (даже для фраз — ключ не переименовываем). `danger_handler` (4c) прокидывает значение в `ReplyParameters(quote=...)` — фраза является точной подстрокой текста (match.group() в регистре текста) → quote корректен. `war_keyword_handler` (4b) значение не использует (только логирует). Оба потребителя не ломаются (T-171-D).

### 32.5 Порядок матчинга: фразы → слова (обоснование)

Фраза «ракетная атака» содержит слово «ракетная», которое ЕСТЬ в слов-списке; «атака беспилотников» содержит «беспилотников». Для **файринга** (сработал/не сработал) порядок не критичен — фильтр сработает в любом случае. Порядок влияет только на содержимое `matched_word`. Решение: **фразы проверяются первыми**, потому что:

1. Фразы специфичнее и длиннее — возвращаемый `matched_word` информативнее («ракетная атака» вместо «ракетная»), quote в danger_handler подсвечивает полную связку;
2. Согласовано с backlog T-171-C («ветка фраз ПЕРЕД словами»);
3. Один цикл по фразам (17 паттернов) дешевле полного перебора слов (118) — при доминировании фразовых триггеров средний матч быстрее.

### 32.6 Edge-кейсы

1. **«в бункер» vs «в бункере»:** паттерн `(?<![а-яё])в бункер(?![а-яё])` в тексте «в бункере» находит кандидата «в бункер», за которым следует «е» — кириллическая строчная из диапазона `[а-яё]` → lookahead **блокирует** матч. Подтверждено: «в бункере» → `False`. Обратное: «спрятаться в бункере» → `True` отдельной фразой (её правая граница — конец строки/пробел). Покрыть тестами (T-171-G).
2. **Омоним «хлопок»:** «хлопок в ладоши»/«хлопки» (аплодисменты) дадут ложное срабатывание — риск принят (D57). «хлопковый» НЕ матчится: после «хлопок» идёт «в» → lookahead блокирует → `False`. «хлопка»/«хлопке» (другие падежи) в списке нет → `False` (сознательно: только журналистские формы).
3. **Регистр:** IGNORECASE покрывает «БПЛА», «В БУНКЕР», «Ракетная Атака»; возврат `match.group()` сохраняет регистр текста (quote в Telegram выглядит естественно).
4. **Фраза в начале/конце строки:** lookbehind на позиции 0 всегда успешен (символа нет — запрета нет), lookahead на конце строки успешен → «в бункер» как всё сообщение матчится.
5. **Пунктуация по краям:** «!в бункер!» матчится («!» — не кириллица). Двойной пробел внутри («в  бункер») НЕ матчится — пробелы литеральные (`re.escape`), принято (D55).
6. **Перекрывающиеся фразы:** «иди в бункер» содержит «в бункер»; «бегом в укрытие» содержит «в укрытие». Список упорядочен **longest-first** — первая сматченная фраза возвращает самую длинную («иди в бункер», а не «в бункер»). Порядок из 32.2 обязателен.
7. **Фраза с «ё»:** новых фраз с «ё» нет («прилёт» удалён вместе с Flight). Python `re.IGNORECASE` не отождествляет «е» ↔ «ё» — поведение зафиксировано, фраз с «ё» не вводим.
8. **Env-оверрайд:** `DANGER_WORDS` в env переопределяет только слова; ветка фраз работает всегда (из дефолтов). Тест: `DangerWordFilter(words=["атака"])` всё равно матчит «в бункер».

### 32.7 Влияние на потребителей (осознанное следствие DRY Epic 17)

| Потребитель | Позиция | Затронут? | Изменение поведения |
|-------------|---------|-----------|---------------------|
| `war_keyword_handler` (`handlers/war_alert.py`) | 4b | ✅ да | Слава перестаёт триггерить одиночные «летит»/«укрытие»/«убежище»/«бункер»/«атака»/«угроза»/«обстрел»; начинает на фразы («в бункер», «ракетная атака») и «хлопок» |
| `war_channel_repost_handler` | 4b | ❌ нет | Работает по `TargetChannelFilter` (каналы), словарь не использует |
| `danger_handler` (`handlers/common.py`) | 4c | ✅ да | Те же изменения словаря для ВСЕХ пользователей; quote теперь может быть фразой |

Оба фильтра используют один `DangerWordFilter` и один `DANGER_WORDS` (DRY-мердж Epic 17, `filters/word_lists.py`). Изменение поведения war_alert — **осознанное следствие единого словаря** (backlog-риск 1). Если понадобится раздельный словарь для F5 — отдельная задача, вне скоупа Epic 23.

### 32.8 Тест-план

**Затронутые существующие тесты (621 baseline):**

`tests/test_filters.py` (TestDangerWordFilter):
- `test_letit_matches` («летит птица») — **ломается** → переписать в негатив: «летит» → `False`
- `test_prilet_matches` («прилет в соседний дом») — **ломается** → негатив: «прилет» → `False`
- `test_ubezhishe_matches` («пройдите в убежище») — **ломается** («пройдите» ≠ фразе «пройти в убежище») → позитив «пройти в убежище» + негатив «убежище» → `False`
- `test_obstrel_matches` («обстрел города») — **ломается** → негатив «обстрел» → `False` / позитив «ракетный обстрел»
- `test_upal_matches` («упал беспилотник») — остаётся зелёным НО из-за «беспилотник»; переписать: негатив «ребёнок упал» → `False`
- `test_sbit_matches` («сбит дрон») — остаётся зелёным НО из-за «дрон»; переписать: негатив «самолёт сбит» → `False`
- `test_bunker_matches` («иди в бункер») — **остаётся зелёным** через фразу «иди в бункер»; адаптировать docstring (тест покрывает фразу)
- `test_ukrytie_matches` («бегом в укрытие») — зелёный через фразу «бегом в укрытие»; адаптировать
- `test_ataka_matches` («атака беспилотников») — зелёный через фразу; адаптировать docstring
- `test_synonyms_all_covered` — **удалить пары**: («летает самолет», True), («прилетел поезд», True), («летят гуси», True), («два бункера», True); **оставить**: («дронов много», True), («беспилотник замечен», True), («ракет не хватит», True)
- `test_multiple_war_words_fires_once` («дрон летит ракета бункер») — зелёный («дрон», «ракета» в списке); текст опционально обновить
- **Без изменений** (зелёные): `test_raketa_matches`, `test_dron_matches`, `test_vspyshka_matches`, `test_vzryv_matches`, `test_otboy_matches`, `test_opasnost_matches`, `test_bpla_matches`, `test_raketnaya_matches`, `test_vnimanie_matches`, `test_bespilotnoy_matches`, `test_bespilotnaya_matches`, `test_opoveshenie_matches`, `test_sirena_matches`, `test_trevoga_matches`, `test_evakuatsiya_matches`, все caption-тесты

`tests/test_common.py` (TestDangerWordFilterExpanded):
- `test_ukrytie_matches` («все в укрытие») — зелёный через «в укрытие»; переписать по T-171-F: позитив «в бункер»/«в убежище» + негатив одиночных «бункер»/«укрытие» → `False`
- `test_bunker_matches` («заходи в бункер») — зелёный через «в бункер»; адаптировать
- `test_sbit_matches` («бпла сбит») — зелёный через «бпла»; docstring обновить или оставить
- `TestDangerPatternBuilder`: `test_parse_danger_words_empty_returns_defaults` / `test_parse_danger_words_default_list_length` (`len(result) > 100`) — **зелёные** (118 > 100); усилить до `== 118` (рекомендация)

`tests/test_edge_cases.py`, `tests/test_war_alert.py` — **без изменений** (handler-тесты вызывают хендлеры напрямую мимо фильтра; edge-кейсы используют «дрон»/«опасность» — слова остаются).

**Новые тесты (T-171-G, ≈25, параметризованные):**

| Группа | Кейсы |
|--------|-------|
| Позитив фраз | все 17 фраз как отдельные сообщения → `True`, `matched_word == фраза в регистре текста` |
| Фраза в контексте | середина («скажи в укрытие быстро»), начало, конец строки |
| Негатив одиночных | «атака», «угроза», «обстрел», «укрытие», «убежище», «бункер», «бомбоубежище», «летит», «прилет», «сбит», «упал», «падение» → `False` |
| Границы фразы | «в бункере» → `False`; «спрятаться в бункере» → `True` |
| Хлопок | «хлопок» → `True`; «хлопки» → `True`; «хлопковый» → `False` |
| Регистр | «В БУНКЕР» → `True`, `matched_word == "В БУНКЕР"`; «Ракетная Атака» → `True` |
| Порядок веток | «ракетная атака дронов» → `matched_word == "ракетная атака"` (фраза раньше слова); «иди в бункер» → полная фраза, не «в бункер» |
| Env-независимость | `DangerWordFilter(words=["атака"])` + «в бункер» → `True` (D55) |
| Caption | фраза в `message.caption` → `True` |

**Итог тестов:** 621 baseline − 0 удалённых (переписываем, не удаляем) + ~25 новых ≈ **646** (фактическое число зафиксировать в T-172).

### 32.9 README / док-синк (v2.21.0)

| Место | Правка |
|-------|--------|
| README строка 5 | версия v2.20.0 → **v2.21.0**; число тестов — по факту T-172 |
| README строка 35 (F5v2) | примеры «дрон, БПЛА, ракета, опасность, тревога, убежище» → убрать «убежище» (только фразы), добавить «в бункер», «ракетная атака» |
| README строка 77 | «(бпла, ракетная, опасность, сирена, атака, угроза, дрон, взрыв, прилет и др. — 187 слов)» → «(118 словоформ + 17 фраз: "ракетная атака", "в бункер" и др.)»; убрать «атака, угроза, прилет» из примеров одиночных |
| README строка 101 | «(187 слов)» → «(118 словоформ + 17 фраз)» |
| README строки 105, 434 | исторические записи «22 → 187» не трогать; добавить блок «Исправлено в v2.21.0 (Epic 23)» с описанием D55–D58 |
| `plans/ARCHITECTURE.md` | Section 32 (эта), заголовок файла (версия/статус), СОДЕРЖАНИЕ + пункт 12 |
| `plans/MEMORY.md`, `plans/board.md` | v2.21.0, состав словаря, статус Epic 23 (T-172-C) |

### 32.10 Риски

| # | Риск | Митигация |
|---|------|-----------|
| R1 | Общий словарь меняет поведение war_alert (4b) и danger (4c) одновременно | Осознанное следствие DRY (Epic 17); задокументировано в 32.7; раздельный словарь — вне скоупа |
| R2 | Омоним «хлопок» (аплодисменты) → ложные срабатывания | Принят (D57); «хлопковый» заблокирован границей |
| R3 | Prod `.env` с явным `DANGER_WORDS` переопределит слова | На проде `DANGER_WORDS` пустой → дефолты; `.env` НЕ менять (T-172-E); ветка фраз от env не зависит (D55) |
| R4 | 621 существующих тестов | Перечень сломанных/зелёных — в 32.8; полный прогон T-171-H; тесты переписываются, не удаляются |
| R5 | Рассинхрон чисел в доках (187/191/119) | Фактический подсчёт из кода — 118; PM-оценка 119 скорректирована в T-172-A |
| R6 | Quote фразой в `ReplyParameters` | `match.group()` — точная подстрока текста в его регистре → quote валиден |
| R7 | «в  бункер» (двойной пробел) не матчится | Литеральные пробелы по D55; принято |
| R8 | Перекрытие фраз («иди в бункер» ⊃ «в бункер») | Longest-first порядок списка (32.2) — покрыто тестом |

### 32.11 Сводка для Builder — точные сигнатуры изменений

1. `filters/word_lists.py`
   - `DANGER_WORDS` — удалить секции Flight/arrival (10), Shelter/bunker (26), Атака/угроза (28), Падение/сбитие (13); в секцию Flash добавить `'хлопок', 'хлопки', 'хлопнуло', 'хлопнул'` → итого **118** форм;
   - `DANGER_PHRASES: list[str]` (НОВАЯ) — 17 фраз в порядке из 32.2 (shelter longest-first, затем attack);
   - обновить docstring модуля («WarWordFilter» больше не существует — упоминание устарело).
2. `filters/danger_word.py`
   - import: `from filters.word_lists import DANGER_WORDS, DANGER_PHRASES`;
   - `_build_phrase_patterns(phrases: list[str]) -> list[re.Pattern]` (НОВАЯ, аналог `_build_danger_patterns`, skip битых через `except re.error` + WARNING);
   - `__init__`: `self._phrase_patterns = _build_phrase_patterns(DANGER_PHRASES)` — всегда дефолты, env-оверрайда нет;
   - `__call__`: ветка фраз ПЕРЕД словами; лог `matched phrase`; возврат `{"matched_word": match.group()}` в обеих ветках;
   - `_build_danger_patterns`, `_parse_danger_words` — БЕЗ изменений.
3. `tests/test_filters.py`, `tests/test_common.py` — правки по 32.8 + новые параметризованные тесты фраз.
4. **НЕ менять:** `handlers/war_alert.py`, `handlers/common.py`, `services/common_relay.py`, `config/settings.py`, `.env.example`, `bot.py` — потребители и конфиг совместимы с новым возвратом (дикт `matched_word`).

### 32.12 Порядок реализации

1. **T-169** (word_lists: Flight/Падение/Shelter удалить, хлопки, 10 shelter-фраз) →
2. **T-170** (word_lists: Атака удалить, 7 attack-фраз) →
3. **T-171** (danger_word: `_build_phrase_patterns` + ветка фраз + все тесты, полный pytest) →
4. **T-172** (README/ARCHITECTURE/MEMORY/board sync v2.21.0, коммит на русском `feat(danger): точная настройка danger-словаря — фразы и журналистские синонимы (v2.21.0)`, деплой, smoke «укрыться в убежище»/«бункер»/«хлопок»/«летит»/«ракетная атака»).

---

@Orchestrator Epic 23 (T-169..T-172) architecture ready — v2.21.0 design passed to @Builder.

---

## 33. Epic 24 — SmartModule: Summary (v2.22.0)

> **Дата:** 2026-08-16
> **Статус:** IMPLEMENTED ✅ (T-174…T-189 @Builder; ревью T-188-D APPROVE WITH FIXES → Approved; Low-фиксы закрыты в T-189; 835 тестов). Фактические решения реализации — 33.16.
> **Цель:** автономный сервис Summary: бот копит все сообщения чата в SQLite, каждые 6 часов (00/06/12/18 Asia/Yekaterinburg) или по `/summary` генерирует токсично-ироничное саммари через LLM (apinet.cloud: `deepseek-v4-flash` + эмбеддинги `gemini-embedding-001`). Трёхуровневая память L1 (окно 6ч) / L2 (сырьё для RAG, `FULL_MEMORY_RETENTION_DAYS`) / L3 (архив sqlite-vec + обязательный фоллбек FTS5).
> **Требования R1–R18 и решения D59–D64:** `plans/backlog.md` Epic 24 (зафиксированы PM 2026-08-16).
> **Исследование R18 (T-173-F):** `plans/RESEARCH.md`, секция «Методология исследования» (context7 — API-key недоступен, duckduckgo — anomaly; рабочие инструменты: exa + webfetch docs.aiogram.dev; даты и источники там).

### 33.1 Ключевые архитектурные решения (summary)

| # | Решение | Обоснование |
|---|---------|-------------|
| **A1** | Все модули — **плоскими файлами** в `services/` и `handlers/` (НЕ подпакет `services/smartmodule/`), префикс имён `summary_*` | Конвенция проекта: `mimic_relay.py`, `common_relay.py`, `olya_relay.py`; подпакетов в `services/` нет |
| **A2** | БД — **общая `local_database.db`** (существующий `DatabaseService`), НЕ отдельный `smartmodule.db` | Миграции уже идут через `_SCHEMA_SQL` (executescript CREATE IF NOT EXISTS), WAL включён, бэкапы единые. Отдельный файл = второй коннект + второй WAL + рассинхрон миграций |
| **A3** | Наблюдатель сбора сообщений — **отдельный роутер `summary_observer_router` на позиции 0a** (самый первый), catch-all, всегда `return UNHANDLED` | Не трогает `dp.update.outer_middleware`, не конфликтует с `MessageCounterMiddleware` (это inner middleware slavik_router). Роутер — по конвенции проекта |
| **A4** | `summary_router` (`/summary`) — **позиция 0b** (сразу после наблюдателя, ДО admin_commands и catch-all роутеров 5/6). Хендлер НИКОГДА не возвращает `UNHANDLED` на своём пути | Команда от Славы не должна долететь до `slavik_catchall_handler` («пошёл нахуй»). Не-`UNHANDLED` возврат останавливает propagation (конвенция раздела 1.2) |
| **A5** | L3-сжатие — **НЕ отдельная джоба APScheduler**, а шаг внутри пайплайна генерации под общим `asyncio.Lock` | Устраняет гонку «сжатие vs генерация» (риск 7 backlog). Джоба одна (cron 0 */6 * * *), `max_instances=1, coalesce=True` |
| **A6** | Фоллбек-каскад памяти: **vec0 KNN → FTS5**; текст архивных фактов пишется в обычную таблицу `smart_archive_facts` (+ её FTS5) ВСЕГДА, эмбеддинги — опционально | Даже без sqlite-vec архив живёт и ищется через FTS5 (R3, D60) |
| **A7** | L2-RAG — **FTS5-поиск по ключевым словам окна L1** (программный запрос, без доп. LLM-вызова) | «Точные совпадения/цитаты» даёт phrase-match FTS5; лишний LLM-вызов = стоимость + таймаут |
| **A8** | Имена участников — **резолвить в момент СОХРАНЕНИЯ** в колонку `author_name`; каскад alias → nickname → username (без @) → user_id | `nickname`/`username` недоступны из БД постфактум; менять алиасы в конфиге можно без миграций |
| **A9** | `SUMMARY_ALIASES` — **JSON-строка** `{"<user_id>": "<alias>"}` | Машиночитаемо, парсится `json.loads` в try/except; проще `user_id:alias,...` для ID с именами |
| **A10** | Промпты — **отдельный модуль `services/summary_prompts.py`** (SYSTEM_PROMPT дословно, R11; v2 — Epic 27, Section 36 + COMPRESS_PROMPT) | Байт-в-байт тест R11 (T-182-A) без примеси логики |
| **A11** | `/summary` НЕ удаляем из чата (в отличие от admin_commands) | Память собирает всё; удаление — опционально, решение за пользователем (backlog-риск 10) |
| **A12** | **Деплой-нота:** для сбора ВСЕХ сообщений группы у бота должна быть отключена privacy mode (**BotFather → /setprivacy → Disable**) | С privacy ON бот в группах видит только команды/упоминания — L1/L2/L3 будут пустыми |
| **A13** | Кросс-зависимости: `httpx>=0.27`, `APScheduler>=3.10,<4`, `sqlite-vec>=0.1.2` (в requirements; `sqlite-vec` — с graceful-fallback, см. 33.11) | RESEARCH T-173-F: MSVC-колесо sqlite-vec с v0.1.2-alpha.9; APScheduler только MemoryJobStore (pickle-ловушка) |
| **A14** | Ответ LLM — постобработка: чанкинг ≤4096 по пробелам + проверка приписки «самым главным шизом…» (дописать при отсутствии) | R12/D63 + гарантия R9 финальной приписки |
| **A15** | Троттлинг — **router-scoped outer middleware** только на `summary_router` (key = chat_id+user_id, TTL из `SUMMARY_THROTTLE_SECONDS`), молчаливый `return` | Не влияет на остальные роутеры и на наблюдателя; спам `/summary` отбрасывается без ответа |

### 33.2 Структура файлов (точные пути)

```
services/summary_prompts.py       # SYSTEM_PROMPT (дословно, R11 v2 — Epic 27), COMPRESS_PROMPT (L3), EXTRACT_PROMPT (35.3), MAX_CHARS_* константы
services/llm_client.py            # LLMClient (провайдер-агностик): generate(), embed(), close(); LLMError-иерархия
services/summary_memory.py        # MemoryManager: L1 окно, L2 FTS5-RAG, L3 сжатие+KNN(+FTS5-фоллбек), retention-клины
services/summary_xml.py           # XmlGroundingBuilder: <chat_history><message …/></chat_history>, экранирование, лимиты
services/summary_aliases.py       # AliasResolver: JSON-парсинг, каскад alias→nickname→username→user_id
services/summary_generator.py     # SummaryGenerator: полный пайплайн + чанкинг + UX-ошибки + шиз-приписка
services/summary_scheduler.py     # SummarySchedulerService: AsyncIOScheduler, cron 0 */6 * * *, generation-lock
services/summary_throttling.py    # ThrottlingMiddleware (BaseMiddleware, in-memory TTL)
handlers/summary.py               # summary_observer_router (0a) + summary_router (0b) + setup_summary()
config/settings.py                # +18 полей (33.8)
.env.example                      # секция SmartModule (T-174-B)
bot.py                            # позиции 0a/0b, wiring on_startup/on_shutdown (33.9)
services/database.py              # _SCHEMA_SQL + методы smart_messages/archive (33.3)
tests/test_summary_*.py           # 9 файлов (33.13)
```

### 33.3 Схема БД (в существующей `local_database.db`, `_SCHEMA_SQL`)

```sql
-- R1: таблица сообщений (+author_name — обоснование A8)
CREATE TABLE IF NOT EXISTS smart_messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER,                 -- NULL для сервисных (не сохраняем их вообще, см. 33.9)
    chat_id      INTEGER NOT NULL,
    text         TEXT,                    -- message.text ИЛИ message.caption (для медиа)
    reply_to_id  INTEGER,                 -- reply_to_message.message_id | NULL
    timestamp    INTEGER NOT NULL,        -- unix epoch секунды (UTC)
    media_type   TEXT NOT NULL DEFAULT 'text',   -- text|photo|video|voice|audio|animation|sticker|document|other
    author_name  TEXT NOT NULL DEFAULT '' -- резолв A8 на момент сохранения
);
CREATE INDEX IF NOT EXISTS idx_smart_messages_chat_ts ON smart_messages(chat_id, timestamp);

-- FTS5-индекс над сырьём L1/L2 (ВСЕГДА доступен, встроенный, без расширений) — фоллбек + L2-RAG
CREATE VIRTUAL TABLE IF NOT EXISTS smart_messages_fts USING fts5(
    text, content='smart_messages', content_rowid='id', tokenize='unicode61'
);

-- L3: архивные факты — обычная таблица (пишется ВСЕГДА при сжатии)
CREATE TABLE IF NOT EXISTS smart_archive_facts (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id   INTEGER NOT NULL,
    fact      TEXT NOT NULL,
    timestamp INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_archive_facts_chat_ts ON smart_archive_facts(chat_id, timestamp);
CREATE VIRTUAL TABLE IF NOT EXISTS smart_archive_facts_fts USING fts5(
    fact, content='smart_archive_facts', content_rowid='id', tokenize='unicode61'
);

-- L3: векторы (создаётся ЛЕНИВО из кода, ТОЛЬКО если sqlite-vec загрузился; dim из конфига)
-- CREATE VIRTUAL TABLE smart_archive USING vec0(
--     embedding float[768] distance_metric=cosine, +fact_id INTEGER, +chat_id INTEGER
-- );
```

**Миграции:** как в проекте — `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS` внутри `_SCHEMA_SQL` (services/database.py:14); старые БД получают новые таблицы при рестарте, данные не трогаются. vec0-таблица создаётся из `MemoryManager.initialize()` (не из executescript — расширение может не загрузиться).

**Методы `DatabaseService` (добавить в services/database.py):**
- `save_smart_message(user_id, chat_id, text, reply_to_id, timestamp, media_type, author_name)` — INSERT + `INSERT INTO smart_messages_fts(rowid, text) VALUES (lastrowid, ?)` (или триггеры; достаточно прямой вставки в том же методе).
- `get_smart_window(chat_id, since_ts, limit)` — L1, **один SQL-проход**: `SELECT … WHERE chat_id=? AND timestamp>=? ORDER BY timestamp DESC LIMIT ?` → реверс ASC.
- `get_smart_raw(chat_id, older_than_ts, limit)` — L2-сырьё (для цитат).
- `delete_smart_messages_older_than(chat_id, cutoff_ts)` — retention L2 (после сжатия), возвращает число удалённых.
- `save_archive_fact(chat_id, fact, timestamp)`, `delete_archive_facts_older_than(chat_id, cutoff_ts)`, `search_archive_fts(chat_id, match_query, limit)` — L3-текстовая ветка.
- `search_messages_fts(chat_id, match_query, limit)` — L2-RAG и фоллбек.
- Vector-методы (`insert_archive_embedding`, `search_archive_knn`) — В `MemoryManager`, НЕ в DatabaseService (они гейтятся по `self._vec_available`; DatabaseService остаётся extension-agnostic).

### 33.4 `services/llm_client.py` — LLMClient (провайдер-агностик, R4/R5)

```python
class LLMError(Exception): ...
class LLMAuthError(LLMError): ...      # 401/403
class LLMRateLimitError(LLMError): ... # 429
class LLMTimeoutError(LLMError): ...   # httpx.TimeoutException
class LLMBadResponseError(LLMError): ...  # кривой JSON / нет content

class LLMClient:
    def __init__(self, base_url: str, api_key: str, chat_model: str,
                 embed_model: str, timeout: float = settings.LLM_TIMEOUT,
                 max_retries: int = settings.LLM_MAX_RETRIES) -> None
    async def generate(self, messages: list[dict[str, str]]) -> str   # choices[0].message.content
    async def embed(self, texts: list[str]) -> list[list[float]]      # data[i].embedding
    async def close(self) -> None                                     # закрыть httpx-сессию
```

- **Одна `httpx.AsyncClient` сессия** на весь процесс (`timeout=httpx.Timeout(timeout, connect=10.0)`), ленивое создание, `close()` в `on_shutdown`.
- Endpoints: `POST {base_url}/chat/completions` и `POST {base_url}/embeddings`, `Authorization: Bearer {api_key}` (contract — RESEARCH §h).
- **Retry:** 429/5xx/timeout → до `max_retries` (default 2) повторов с backoff `0.5s * 2**n`; 401/403 — без повторов → `LLMAuthError`.
- **R3:** `embed()` сам по себе НЕ глотает ошибки (бросает `LLMError`) — try/except на стороне `MemoryManager` (33.5).
- Логи: модель, URL, размер запроса/ответа, время запроса; сырой текст генерации логирует ВЫЗЫВАЮЩИЙ (33.7, R14) — клиент не знает про Logtail-политику.

### 33.5 `services/summary_memory.py` — MemoryManager (L1/L2/L3 + фоллбек)

```python
class MemoryManager:
    def __init__(self, db: DatabaseService, llm: LLMClient) -> None
    async def initialize(self) -> bool
        # 1) try: await db.db.enable_load_extension(True); await db.db.load_extension(sqlite_vec.loadable_path())
        #    except Exception → self._vec_available = False, WARNING-лог (R3 — не ронять бота)
        # 2) if available: CREATE VIRTUAL TABLE smart_archive USING vec0(embedding float[?] …, +fact_id, +chat_id)
        # 3) финально: await db.db.enable_load_extension(False)
        # возвращает self._vec_available

    async def get_window_messages(self, chat_id: int) -> list[Row]
        # L1: db.get_smart_window(chat_id, since=now-SUMMARY_WINDOW_HOURS, limit=SUMMARY_MAX_WINDOW_MESSAGES)

    async def search_long_term(self, chat_id: int, keywords: list[str], limit: int) -> list[Row]
        # L2-RAG: FTS5 `text : "kw1" OR "kw2" …` (санитайз кавычек/звёздочек, RESEARCH §f) → ORDER BY rank

    async def vector_search(self, chat_id: int, query: str, limit: int) -> list[str]
        # L3: if self._vec_available:
        #        try: v = await self.llm.embed([query])        # ← try/except (R3)
        #             KNN: SELECT fact_id FROM smart_archive WHERE embedding MATCH ? AND chat_id=? AND k=? → join facts
        #        except Exception: → fts-fallback
        #      if not available / exception: → self._fts_search(chat_id, query, limit)  # smart_archive_facts_fts
        #      return [fact_text, …]

    async def compress_and_purge(self, chat_id: int) -> None
        # 1) SELECT старые (> FULL_MEMORY_RETENTION_DAYS) пачками SUMMARY_COMPRESS_BATCH (default 100)
        # 2) на каждую пачку: llm.generate(COMPRESS_PROMPT + тексты) → факты (построчно, до 10)
        # 3) save_archive_fact(...) ВСЕГДА; если _vec_available: try embed+INSERT в vec0 → except: WARNING, факт живёт только в FTS5
        # 4) delete_smart_messages_older_than(chat_id, cutoff)  — ТОЛЬКО после успешного сохранения фактов пачки
        # 5) delete_archive_facts_older_than(chat_id, now - ARCHIVE_MEMORY_RETENTION_DAYS) (+ удалить их векторы rowid)
        # ошибка LLM на пачке → logger.exception, пачка НЕ удаляется (не теряем сырьё), конвейер продолжает
```

**COMPRESS_PROMPT (захардкодить в summary_prompts.py; маленькие буквы — стиль бота):**
```
ты — сжиматель истории чата. из приведённого ниже списка сообщений выдели отдельные темы и факты, которые могут пригодиться для будущих саммари чата. каждый факт верни отдельной строкой. не используй нумерацию, маркдаун и смайлы. пиши с маленькой буквы. фактов должно быть не больше 10, только самое важное.
```

**Гонка (backlog-риск 7):** `compress_and_purge` вызывается ТОЛЬКО из `SummaryGenerator.generate_summary()` (33.7) под его `asyncio.Lock` — отдельной джобы нет (A5).

### 33.6 `services/summary_xml.py` + `services/summary_aliases.py`

**XmlGroundingBuilder (R6):**
- `build(messages: list[Row], aliases: AliasResolver) -> str`:
  `<chat_history>` + на каждое сообщение `<message id="{id}" timestamp="{iso8601}" author="{author}" reply_to_id="{rid|''}" type="{media_type}">{escaped}</message>` + `</chat_history>`.
- Экранирование: `xml.sax.saxutils.escape(text)` (`&`→`&amp;`, `<`→`&lt;`, `>`→`&gt;`) + вырезать непечатаемые control-символы (`re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', s)`).
- `author`: `author_name` из БД; пусто → каскад AliasResolver (страховка старых записей).
- Медиа: `media_type != 'text'` и нет caption → тело = описание: photo→`[фото]`, video→`[видео]`, voice→`[голосовое]`, audio→`[аудио]`, animation→`[гифка]`, sticker→`[стикер]`, document→`[файл]`, other→`[медиа]`; caption есть → caption + описание.
- Лимиты окна (риск 6): последние `SUMMARY_MAX_WINDOW_MESSAGES` (default 500) сообщений; каждое обрезается до `SUMMARY_MAX_MESSAGE_CHARS` (default 2000); суммарно не более `SUMMARY_MAX_CONTEXT_CHARS` (default 120000) — жёсткий кап до среза сообщения.

**AliasResolver (R7/D61):**
- `__init__(raw_json: str)`: `json.loads(raw_json)` в try/except → `{}` + WARNING; ключи — строки user_id → alias. Кэш резолва per-process.
- `resolve(user_id: int, nickname: str | None, username: str | None) -> str`:
  1. alias из словаря (если есть) → 2. nickname (`first_name`+`last_name` через пробел, если непусто) → 3. `username.lstrip('@')` (если есть) → 4. `str(user_id)`. **@ в результатах исключён на всех уровнях** — тест.
- Применение: в наблюдателе при сохранении (A8); в XML — fallback для `author_name=''`.

### 33.7 `services/summary_generator.py` — SummaryGenerator (полный конвейер)

```python
class SummaryGenerator:
    def __init__(self, memory: MemoryManager, xml: XmlGroundingBuilder,
                 llm: LLMClient, bot: Bot) -> None
        self._lock = asyncio.Lock()   # дедупликация manual/cron (A5)

    async def generate_and_send(self, chat_id: int) -> None:
        async with self._lock:        # второй вызов ждёт/отваливается (см. 33.10)
            await self._run(chat_id)

    async def _run(self, chat_id: int) -> None:
        try:
            await self.memory.compress_and_purge(chat_id)          # L3-сжатие ПЕРЕД выборкой (A5)
            rows = await self.memory.get_window_messages(chat_id)  # L1, один проход
            if not rows:  # пустое окно → не генерировать, INFO-лог, выход без сообщения
                return
            xml_context = self.xml.build(rows, aliases)
            keywords = self._extract_keywords(rows)                # топ-токены окна (частотный словарь, стоп-слова «ёпта/ну/и/а…»)
            l2_quotes = await self.memory.search_long_term(chat_id, keywords, settings.SUMMARY_RAG_L2_LIMIT)
            l3_facts  = await self.memory.vector_search(chat_id, " ".join(keywords), settings.SUMMARY_RAG_L3_LIMIT)
            user_content = self._compose_user_content(xml_context, l2_quotes, l3_facts)  # <memory>+<facts> секции
            max_symbols = settings.MAX_SUMMARY_PARTS * 4000 - 200
            system = SYSTEM_PROMPT.replace("{max_symbols}", str(max_symbols))   # ДОСЛОВНО (R11 v2 — Epic 27); {username} — литерал, str.format дал бы KeyError
            raw = await self.llm.generate([{"role": "system", "content": system},
                                           {"role": "user", "content": user_content}])
            logger.info("summary LLM raw response | chat_id=%s | len=%d | raw=%r", chat_id, len(raw), raw)  # R14
            text = self._ensure_shiz_postfix(raw, rows)              # нет приписки → дописать (A14)
            await self._send_chunked(chat_id, text)
        except LLMError/httpx-ошибки:
            logger.exception(...); await self._send_ux(chat_id, "не смог сделать саммари потому что упал апи")
        except aiosqlite.Error / sqlite3.Error:
            logger.exception(...); await self._send_ux(chat_id, "база данных подавилась")
        except Exception:
            logger.exception(...); await self._send_ux(chat_id, "не смог сделать саммари")  # без техдеталей
```

- `_ensure_shiz_postfix`: `if "самым главным шизом объявляется" not in text` → выбрать самого активного автора окна (счётчик по author_name) → `text += "\nсамым главным шизом объявляется " + имя`. Если итог > 4096*parts — приписка отдельным последним чанком.
- `_send_chunked`: `_chunk_by_whitespace(text, 4096)` → по каждому чанку `await bot.send_message(chat_id, chunk)`; **между чанками `await asyncio.sleep(settings.SUMMARY_CHUNK_DELAY)`** (default 1.0s); `except TelegramRetryAfter as e: await asyncio.sleep(e.retry_after)` и повтор чанка один раз (RESEARCH §g).
- `_chunk_by_whitespace(text, limit)` — чистая функция (для тестов): жадно накапливает слова, разрыв только по пробелам; чанк ≤ limit; одиночное слово длиннее limit — не режется (Telegram сам откажет, лог WARNING).
- UX-фразы (R13): маленькая буква, без эмодзи/техдеталей; отправляются только при первом сбое за прогон (не спамить чанками об ошибке).

### 33.8 Конфиг — `config/settings.py` (24 поля, хелперы `_env_*` существующие)

```python
# ── SmartModule: Summary (Epic 24) ────────────────────────────
LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")                              # R5/D64
LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "https://apinet.cloud/v1")
LLM_MODEL_NAME: str = os.getenv("LLM_MODEL_NAME", "deepseek-v4-flash")
EMBEDDING_MODEL_NAME: str = os.getenv("EMBEDDING_MODEL_NAME", "gemini-embedding-001")
LLM_TIMEOUT: float = _env_float("LLM_TIMEOUT", 60.0)
LLM_MAX_RETRIES: int = _env_int("LLM_MAX_RETRIES", 2)
EMBEDDING_DIM: int = _env_int("EMBEDDING_DIM", 768)                          # dim vec0; gemini-embedding-001 = 768
SUMMARY_ENABLED: bool = _env_bool("SUMMARY_ENABLED", True)
SUMMARY_WINDOW_HOURS: float = _env_float("SUMMARY_WINDOW_HOURS", 6.0)
FULL_MEMORY_RETENTION_DAYS: int = _env_int("FULL_MEMORY_RETENTION_DAYS", 30)
ARCHIVE_MEMORY_RETENTION_DAYS: int = _env_int("ARCHIVE_MEMORY_RETENTION_DAYS", 90)
MAX_SUMMARY_PARTS: int = _env_int("MAX_SUMMARY_PARTS", 1)
SUMMARY_TIMEZONE: str = os.getenv("SUMMARY_TIMEZONE", "Asia/Yekaterinburg")
ALLOWED_SUMMARY_IDS: tuple[int, ...] = _env_int_tuple("ALLOWED_SUMMARY_IDS", ())
SUMMARY_ALIASES: str = os.getenv("SUMMARY_ALIASES", "")                      # JSON {"<user_id>": "<alias>"}
SUMMARY_THROTTLE_SECONDS: float = _env_float("SUMMARY_THROTTLE_SECONDS", 60.0)
SUMMARY_CHUNK_DELAY: float = _env_float("SUMMARY_CHUNK_DELAY", 1.0)
SUMMARY_TARGET_CHAT_IDS: tuple[int, ...] = _env_int_tuple("SUMMARY_TARGET_CHAT_IDS", ())  # пусто = все чаты с сообщениями
SUMMARY_MAX_WINDOW_MESSAGES: int = _env_int("SUMMARY_MAX_WINDOW_MESSAGES", 500)
SUMMARY_MAX_MESSAGE_CHARS: int = _env_int("SUMMARY_MAX_MESSAGE_CHARS", 2000)
SUMMARY_MAX_CONTEXT_CHARS: int = _env_int("SUMMARY_MAX_CONTEXT_CHARS", 120000)
SUMMARY_RAG_L2_LIMIT: int = _env_int("SUMMARY_RAG_L2_LIMIT", 10)
SUMMARY_RAG_L3_LIMIT: int = _env_int("SUMMARY_RAG_L3_LIMIT", 10)
SUMMARY_COMPRESS_BATCH: int = _env_int("SUMMARY_COMPRESS_BATCH", 100)
```

Все ключи D59 покрыты; дефолты `FULL_MEMORY_RETENTION_DAYS=30`, `ARCHIVE_MEMORY_RETENTION_DAYS=90` зафиксированы @Architect (были «ориентиры»). `.env.example` — та же секция с комментариями; `LLM_API_KEY=` пустой (R17).

### 33.9 `bot.py` — порядок регистрации и wiring (CRITICAL, не менять порядок)

```
# 0a. SmartModule observer (Epic 24) — catch-all, сохраняет ВСЁ, возвращает UNHANDLED
dp.include_router(summary_observer_router)
# 0b. SmartModule /summary (Epic 24) — ДО admin_commands и catch-all 5/6
dp.include_router(summary_router)
# 0. Admin test commands (Epic 10)
dp.include_router(admin_commands_router)
# … (1 … 6 без изменений)
```

**on_startup() (после существующих setup-ов):**
```python
if settings.SUMMARY_ENABLED:
    llm_client = LLMClient(settings.LLM_BASE_URL, settings.LLM_API_KEY,
                           settings.LLM_MODEL_NAME, settings.EMBEDDING_MODEL_NAME)
    memory = MemoryManager(db, llm_client)
    vec_ok = await memory.initialize()                      # A6: try/except внутри
    logger.info("SmartModule: sqlite-vec %s", "available" if vec_ok else "UNAVAILABLE — FTS5 fallback (R3)")
    aliases = AliasResolver(settings.SUMMARY_ALIASES)
    xml_builder = XmlGroundingBuilder()
    generator = SummaryGenerator(memory, xml_builder, llm_client, bot)
    setup_summary(generator)                                # инъекция в handlers/summary.py
    _summary_service = SummarySchedulerService(generator, db)   # module-level (для on_shutdown)
    _summary_service.start()                                # ДО dp.start_polling (RESEARCH §c)
    logger.info("SmartModule Summary (Epic 24) initialized (TZ=%s)", settings.SUMMARY_TIMEZONE)
```
**on_shutdown():** `if _summary_service: _summary_service.shutdown(); await llm_client.close()` (refs — module-level в bot.py; текущий on_shutdown их не видит).

**Наблюдатель (`handlers/summary.py`, router 0a):**
- Фильтр: `F.message` (сообщения); пропуск: `from_user is None` ИЛИ `from_user.id == bot.id` (свои сообщения не пишем) ИЛИ `text is None and caption is None` (чистые сервисные).
- Сохранение: `media_type` из полей (`text → 'text'`; `photo → 'photo'`; `video/video_note → 'video'`; `voice → 'voice'`; `audio → 'audio'`; `animation → 'animation'`; `sticker → 'sticker'`; `document → 'document'`; иначе `'other'`); `text = message.text or message.caption`; `reply_to_id = message.reply_to_message.message_id or None`; `author_name = aliases.resolve(...)`.
- `try/except` вокруг `db.save_smart_message` → WARNING-лог, НЕ ронять event loop; **всегда `return UNHANDLED`** (включая пропуски) — propagation до остальных роутеров гарантирован (конвенция разделов 1.2/30).
- `MessageCounterMiddleware` (inner middleware slavik_router) не затронут: он живёт в другом роутере и считает только Славу.

**`summary_router` (0b, `/summary`):**
```python
@summary_router.message(Command("summary"))
async def cmd_summary(message: types.Message):
    user_id = message.from_user.id if message.from_user else 0
    allowed = settings.ALLOWED_SUMMARY_IDS
    if allowed and user_id not in allowed:          # R9/D62
        logger.debug("[/summary] user %s not in ALLOWED_SUMMARY_IDS", user_id)
        return                                       # молчаливо поглотить (НЕ UNHANDLED → до Славы не долетит)
    await _generator.generate_and_send(message.chat.id)   # внутри: lock + пайплайн + UX-ошибки
    return                                           # None → propagation остановлен (A4)
```
- `setup_summary(generator)` — паттерн инъекции проекта (`setup_olya` и др.).
- `SUMMARY_ENABLED=False` → роутеры не регистрируются, `setup_summary` не вызывается; бот работает как раньше.

### 33.10 `services/summary_scheduler.py` — APScheduler (R8)

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

class SummarySchedulerService:
    def __init__(self, generator: SummaryGenerator, db: DatabaseService) -> None:
        self._generator = generator
        self._db = db
        self._scheduler = AsyncIOScheduler(timezone=settings.SUMMARY_TIMEZONE)  # MemoryJobStore (default) — ТОЛЬКО он

    def start(self) -> None:
        self._scheduler.add_job(self._tick, CronTrigger(hour="0,6,12,18", minute=0),
                                id="summary_job", replace_existing=True,
                                max_instances=1, coalesce=True)     # антигонка: пропуск совпавших запусков
        self._scheduler.start()                                      # до start_polling (bot.py 33.9)

    async def _tick(self) -> None:
        target = settings.SUMMARY_TARGET_CHAT_IDS or await self._db.get_smart_chat_ids()  # DISTINCT chat_id
        for chat_id in target:
            await self._generator.generate_and_send(chat_id)         # общий asyncio.Lock = дедуп с /summary
    async def shutdown(self) -> None:
        self._scheduler.shutdown(wait=False)
```

- **Дедупликация ручной/авто (A5):** и джоба, и `/summary` идут через `SummaryGenerator.generate_and_send` → общий `asyncio.Lock`; второй одновременный запуск просто дожидается, `max_instances=1`+`coalesce` глушат совпавшие тики; троттлинг (`SUMMARY_THROTTLE_SECONDS`, default 60s) отсекает повторные ручные вызовы в окне.
- Существующий `SchedulerService` (DeadPage no-op) НЕ трогаем.

### 33.11 `services/summary_throttling.py` — ThrottlingMiddleware (R10)

```python
class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, throttle_seconds: float = settings.SUMMARY_THROTTLE_SECONDS) -> None:
        self._throttle_seconds = throttle_seconds
        self._last: dict[tuple[int, int], float] = {}          # (chat_id, user_id) → monotonic ts
    async def __call__(self, handler, event, data):
        if isinstance(event, Message) and (event.text or "").startswith("/summary"):
            key = (event.chat.id, event.from_user.id if event.from_user else 0)
            now = time.monotonic()
            last = self._last.get(key)
            if last is not None and (now - last) < self._throttle_seconds:
                logger.info("[/summary] throttled | chat=%s user=%s", *key)
                return                                          # ← НЕ вызывать await handler(event, data) (RESEARCH §a)
            self._last[key] = now
        return await handler(event, data)
```

Регистрация: `summary_router.message.outer_middleware(ThrottlingMiddleware(...))` — **только** на summary_router (не dp-level; наблюдатель и прочие роутеры не затронуты). Хранилище in-memory dict (сброс при рестарте — приемлемо, R10).

### 33.12 Observability (R14) и система промптов (R11)

- **Логирование:** существующая система — `logging.basicConfig` + `LogtailHandler(LOGTAIL_SOURCE_TOKEN)` в bot.py (уже на root logger) → новые модули берут `logging.getLogger(__name__)` и ничего не настраивают. Sentry уже инициализирован.
- Поля/уровни: INFO — этапы пайплайна (window_size, rag_hits_l2/l3, model, request_len, latency_ms, chunks_sent); `logger.info("summary raw LLM response | chat_id=%s | raw=%r", …)` — **сырой ответ LLM в лог** (R14); WARNING — фоллбеки (vec недоступен, embed упал, пачка сжатия пропущена); ERROR+`logger.exception` — полные стектрейсы всех отказов.
- **`services/summary_prompts.py`:** `SYSTEM_PROMPT` — ДОСЛОВНО из backlog (R11; v3 — Epic 28, строки **1518–1540**, Section 37), плейсхолдеры `{max_symbols}` (рантайм-подстановка) и `{username}` (литерал для LLM); `COMPRESS_PROMPT` — из 33.5; тест байт-в-байт (T-182-A). Промпт НЕ логировать целиком (тяжёлый; достаточно `len`).

### 33.13 Тестовая стратегия (R14/R15, 672 существующих не ломать)

| Файл | Кейсы (моки) |
|------|--------------|
| `tests/test_summary_prompts.py` | SYSTEM_PROMPT байт-в-байт = backlog-текст (R11 v3 — Epic 28, строки 1518–1540); набор плейсхолдеров `{max_symbols, username}` (D72); `{max_symbols}` подстановка через replace; COMPRESS_PROMPT непуст |
| `tests/test_llm_client.py` | `httpx.MockTransport`: успех generate/embed; 401→LLMAuthError; 429→retry→успех; 429×N→LLMRateLimitError; timeout→LLMTimeoutError; кривой JSON→LLMBadResponseError; заголовки Bearer/base_url/модель |
| `tests/test_summary_memory.py` | aiosqlite in-memory + fake LLMClient: save→window границы окна (вкл/искл края); search_long_term (FTS5 phrase/prefix, санитайз `*"`); vector_search: vec_available=False→FTS5; embed бросает→FTS5; compress_and_purge (факты сохранились, сырьё удалено, retention-архива 90д, ошибка LLM→пачка не удалена); инициализация без sqlite-vec (monkeypatch loadable_path→битый путь) → `_vec_available=False` без падения |
| `tests/test_summary_xml.py` | структура XML (атрибуты id/timestamp/author/reply_to_id/type); экранирование `<>&"`; control-символы вырезаны; media→описание (`[фото]` и т.п.); caption+медиа; лимиты messages/chars; пустой список → пустой `<chat_history/>` |
| `tests/test_summary_aliases.py` | каскад 4 уровней (alias→nickname→username без @→user_id); `@` отсутствует во всех ветках; JSON битый→`{}`+WARNING; JSON ок |
| `tests/test_summary_generator.py` | fake memory/llm/bot: полный пайплайн (порядок вызовов, max_symbols=3800 при parts=1); пустое окно→без LLM-вызова; LLMError→«не смог сделать саммари потому что упал апи»; sqlite-ошибка→«база данных подавилась»; `_ensure_shiz_postfix` (есть/нет приписки, самый активный автор); `_chunk_by_whitespace` (≤4096, разрыв по пробелам, длинное слово); паузы между чанками (fake sleep); TelegramRetryAfter→sleep+повтор |
| `tests/test_summary_scheduler.py` | CronTrigger hour="0,6,12,18" minute=0 (внутренний атрибут); max_instances/coalesce; TZ Asia/Yekaterinburg; MemoryJobStore (нет add_jobstore); shutdown без ошибок; get_smart_chat_ids fallback |
| `tests/test_summary_handlers.py` | `/summary` allowed пуст→всем; непуст→только ID; запрещённый→молча (нет ответов, propagation остановлен); observer: обычное сообщение→save+UNHANDLED; от бота/сервисное→skip+UNHANDLED; save упал→WARNING, UNHANDLED, не падает; ИНТЕГРАЦИОННЫЙ: Dispatcher со всеми 13 роутерами (mock-контекст) — `/summary` от Славы НЕ триггерит «пошёл нахуй»/photo/mimic/vasya |
| `tests/test_summary_throttling.py` | первый вызов→handler вызван; повтор <TTL→handler НЕ вызван, ответов нет (молчание); после TTL (monkeypatch time.monotonic)→снова вызван; не-`/summary` события не троттлятся |
| `tests/test_database.py` (доп.) | новые таблицы в `_SCHEMA_SQL` создаются на существующей БД (миграция); save/get_window/delete/archive методы |

Стиль тестов — существующие фикстуры (`make_message`, `mock_bot` в conftest.py; message.delete/answer — AsyncMock). Полный прогон в T-188-C: **672 baseline + ~120 новых, 0 регрессий** (число уточнить по факту).

### 33.14 Риски и решения (backlog-риски 1–12 + новые)

| # | Риск | Решение (секция) |
|---|------|------------------|
| 1 | `/summary` от Славы → параллельный «пошёл нахуй» | summary_router на 0b ДО catch-all 5/6; хендлер никогда не возвращает UNHANDLED (33.9) |
| 2 | Наблюдатель vs MessageCounterMiddleware | Отдельный роутер 0a с UNHANDLED; counter — inner middleware другого роутера (33.9) |
| 3 | Отдельный файл БД | НЕТ — общая `local_database.db`, миграции executescript (33.3) |
| 4 | sqlite-vec на Windows MSVC | `sqlite-vec>=0.1.2` (MSVC-колесо, RESEARCH §e/T-173-F); try/except в `initialize()` → FTS5 (33.5) |
| 5 | APScheduler jobstore | ТОЛЬКО MemoryJobStore; версия `>=3.10,<4` в requirements (33.10) |
| 6 | Окно 6ч > контекст LLM | Капы `SUMMARY_MAX_WINDOW_MESSAGES=500` / `SUMMARY_MAX_MESSAGE_CHARS=2000` / `SUMMARY_MAX_CONTEXT_CHARS=120000` (33.8) |
| 7 | Гонка L3-сжатия и генерации | Сжатие — шаг пайплайна под общим `asyncio.Lock`; `max_instances=1, coalesce=True` (33.5/33.10) |
| 8 | Формат SUMMARY_ALIASES | JSON `{"<user_id>": "<alias>"}`, `json.loads` в try/except (33.6) |
| 9 | Prod .env | T-191-B: добавить `LLM_API_KEY` (+ опциональные оверрайды); дефолты работают без оверрайдов |
| 10 | Удалять ли `/summary` | НЕ удаляем (A11); при желании пользователя — отдельная микро-задача |
| 11 | Механика RAG L2 | FTS5 keyword/phrase-поиск из токенов L1, без доп. LLM-вызова (33.5) |
| 12 | Rate limits Telegram | `SUMMARY_CHUNK_DELAY` между чанками + `TelegramRetryAfter`-обработка (33.7) |
| Н1 | **Privacy mode бота** | Деплой-нота A12: BotFather `/setprivacy` → Disable, иначе бот в группах не видит сообщения → память пустая |
| Н2 | Эмбеддинги недоступны, а sqlite-vec доступен | L3-записи только текст+FTS5, vec0 не заполняется; поиск всегда FTS5 — деградация незаметна (33.5) |
| Н3 | LLM_API_KEY пуст на проде | `generate()` бросает LLMAuthError → UX «не смог сделать саммари потому что упал апи» + стектрейс в Logtail; бот не падает |
| Н4 | Рост smart_messages | Сжатие+удаление в каждом прогоне; при долгом простое — первый же прогон сожмёт всё старше 30д |

### 33.15 Сводка для Builder — порядок и границы (T-174 → T-189)

1. **T-174** — `config/settings.py` (33.8) + `.env.example` (+ `requirements.txt`: `httpx>=0.27`, `APScheduler>=3.10,<4`, `sqlite-vec>=0.1.2`).
2. **T-175** — `services/database.py`: `_SCHEMA_SQL` + 7 методов (33.3).
3. **T-176** — L1/L2 в `MemoryManager` (33.5).
4. **T-178** — `services/llm_client.py` (33.4). **T-182** — `services/summary_prompts.py` (дословно!).
5. **T-177 + T-179** — L3 + FTS5-фоллбек (33.5). **T-180/T-181** — XML + алиасы (33.6).
6. **T-185** — ThrottlingMiddleware (33.11). **T-184** — `handlers/summary.py` + позиции 0a/0b в `bot.py` (33.9).
7. **T-183** — SummarySchedulerService (33.10) + wiring bot.py (33.9). **T-186** — чанкинг+UX (33.7).
8. **T-187** — логи/сырые ответы (33.12). **T-188** — тесты (33.13) + полный pytest + ревью @Reviewer (T-188-D).
9. **T-189** — README/доки v2.22.0; **T-190** — коммит на русском; **T-191** — деплой (+ BotFather /setprivacy Disable, A12).

**НЕ менять:** существующие 12 роутеров, их handlers, `MessageCounterMiddleware`, `SchedulerService` (DeadPage), `CommonRelay`/`OlyaRelay`/`MimicRelay` — весь Epic 24 живёт в новых файлах + точечные правки `bot.py`/`database.py`/`settings.py`.

### 33.16 Фактические решения @Builder (T-174…T-189, ревью T-188-D APPROVED)

> Подтверждено реализацией и тестами (829→835 тестов, 0 регрессий). Ревью: APPROVE WITH FIXES → Approved; Low-2/Low-3 закрыты в T-189.

- **sqlite-vec 0.1.9 работает на Windows** (PyPI-колесо есть, vec0 грузится) — риск MSVC из 33.14 не реализовался, но graceful-fallback FTS5 реализован и покрыт тестом (monkeypatch битого `loadable_path`).
- **vec0 0.1.x не поддерживает JOIN внутри KNN-запроса** (ошибка «illegal WHERE constraint on auxiliary column») → KNN top-k выбирает `fact_id, chat_id, distance` отдельным запросом, фильтр по чату и выборка фактов — в Python.
- **FTS5 unicode61 без стемминга** → `build_fts_query` строит префиксные запросы `"kw"*` (пользовательские `"`/`*` санитайзятся). Это интерпретация «phrase/prefix» из 33.13.
- **APScheduler 3.11**: `CronTrigger` требует **явный** `timezone` (системный TZ протекает иначе — проверено); `AsyncIOScheduler._shutdown` исполняется через `call_soon_threadsafe` → в `shutdown()` добавлен `await asyncio.sleep(0)` + защита от `SchedulerNotRunningError`.
- **`{username}` в SYSTEM_PROMPT ломает `str.format`** → `{max_symbols}` подставляется через `replace`, `{username}` остаётся литералом (R11 не нарушен, тест байт-в-байт зелёный). Верно и для v2 (Epic 27): `{username}` в тексте дважды — `.replace` сохранён (36.1 C2).
- **`F.message` как фильтр не матчит события** (magic-атрибут) → наблюдатель зарегистрирован как `@summary_observer_router.message()` без фильтра; роутер `message`-наблюдателя и так матчит только сообщения.
- **Наблюдатель**: «нет text И caption» интерпретировано как «нет текста И нет медиа» — медиа без caption сохраняются с `text=NULL` (иначе R6 «описание медиа» нереализуемо), чистые сервисные (join/pin и т.п., без медиа) пропускаются. Подтверждено ревью.
- **compress_and_purge**: удаление сырья — пачками по ids после успешного сохранения фактов (bulk-cutoff в цикле давал бесконечный повтор); `delete_smart_messages_older_than` сохранён в API DatabaseService.
- **`SUMMARY_CHUNK_DELAY=2.0`** (E9) — осознанное отклонение от дизайна 1.0 (лимиты Telegram: 1 msg/s/чат, 20/мин группа). Зафиксировано в README.
- **Low-2**: `<memory>`/`<facts>` проходят то же экранирование (`escape_xml_text` из summary_xml), что и `<chat_history>`.
- **Low-3**: троттлинг отрезает суффикс `@BotName` перед проверкой команды.
- **Low-4** (нет жёсткого капа чанков по `MAX_SUMMARY_PARTS` — лимит enforced промптом) и **Low-5** (location/contact/dice не сохраняются) — зафиксированы в README как осознанные решения.
- Живой smoke-тест apinet.cloud с Windows-машины @Builder невозможен (сеть не пускает) — контракт покрыт MockTransport-тестами; живая проверка — T-191-D.

## 34. Epic 25 — Багфикс «/summary не реагирует» + удаление команды (v2.23.0)

> **Дата:** 2026-08-16
> **Статус:** DESIGN ✅ (T-192 RCA + T-193 дизайн, @Architect). → T-194/T-195 READY FOR BUILDER (после PM-аппрува).
> **Цель:** устранить «тишину» после `/summary` (RCA T-192), добавить ack-механику (D66) и best-effort удаление команды из чата (D65). Требования R25-1…R25-4 — `plans/backlog.md` Epic 25.

### 34.1 Ключевые решения (summary-fix)

| # | Решение | Обоснование |
|---|---------|-------------|
| **B1** | Ack при ручном `/summary` — «ща гляну, подожди» **отдельным** `send_message` (НЕ reply/answer), ДО `generate_and_send` | Закрывает H-A: при LLM до ~3 мин (60s timeout × 3 попытки + compress-батчи) пользователь сразу видит реакцию. Не reply — команда тут же удаляется (B7), reply на удалённое сообщение выглядит криво. Отдельное сообщение не пересекается с чанкингом (A14) |
| **B2** | `generate_and_send(chat_id, manual: bool = False)` — флаг источника вызова | Cron-джоба НЕ шлёт ack и UX пустого окна (не будить чат ночью); ручной вызов — шлёт. UX-сбои (R13) шлются обоим (чат видит «упал апи» и от cron — это честно). Сигнатура обратно совместима: scheduler не меняется |
| **B3** | Троттлинг: **валидировать mention в middleware** (как aiogram `Command`-фильтр): чужая mention → НЕ потреблять слот троттлинга; своя/без mention → троттлить как раньше. Молчание при троттлинге **ОСТАЁТСЯ** (R8/R10 by design) + INFO-лог с `remaining_seconds` | **Первопричина бага** (доказательства 34.2): `/summary@RofloslavBot` (чужой бот) сжёг слот, повтор `/summary` через 12с молча сглотился. Low-3 (`/summary@НашБот`) не ломается — свой mention по-прежнему матчится. R8 не нарушен — прерывание остаётся молчаливым |
| **B4** | Пустое окно L1: `manual=True` → UX «тут тишина, саммарить нечего»; `manual=False` (cron) → только INFO-лог | H-B: молчаливый return заменён UX для ручных вызовов; cron не спамит 4 раза в сутки |
| **B5** | Занятый `asyncio.Lock`: `manual=True` → «уже делаю саммари, подожди», затем **встать в очередь** (не отваливаться); `manual=False` → INFO-лог и в очередь | H-D: не стоять молча. Отказ от таймаута-отвала: пользователь явно попросил саммари — дождаться честнее, чем молча отвалить. Возможный двойной ответ (cron дописал → manual дождался и тоже дописал) — приемлемо, покрывается логом `lock busy — queued` |
| **B6** | UX-сбои (LLM/БД/генерик) уже реализованы (33.7) и достижимы во всех путях `_run`; добавить страховку `_generator is None` в `cmd_summary` → UX «не смог сделать саммари» + WARNING | H-F закрыт превентивно: любой отказ конвейера → UX-попытка; отказ самого UX → `logger.exception` (существующий `_send_ux`) |
| **B7** | Удаление команды: `await message.delete()` в `cmd_summary` **сразу после ack** (НЕ в `finally`), try/except → WARNING при отказе | Команда — мусор; `finally` отложил бы удаление на 3+ мин пайплайна. В группах без админ-права `delete_messages` → `TelegramForbiddenError` → WARNING, не падаем. Удаляется только исходный `message_id` — ack/саммари не задеваются (отдельные сообщения). При denied-ветке (R9) команда НЕ удаляется (чужое не трогаем) |
| **B8** | Логирование каждого состояния (34.7): triggered / denied / throttled+remaining / ack sent / window empty+manual / lock busy / llm ok-fail / chunks sent / command deleted | «Тишина» должна быть диагностируема из Better Stack (R14); `[/summary] denied` поднят с DEBUG до INFO |
| **B9** | Наблюдатель (0a) НЕ сохраняет команды `/summary*` в `smart_messages` | Команды — не контент чата; на проде в БД уже лежат 2 таких строки (id 68/69). UNHANDLED-контракт и счётчик сообщений не меняются |

### 34.2 RCA T-192 — факты с прода и вывод (доказательства)

**Среда:** nik@198.46.175.136 (Posh-SSH), `/var/www/admin_bot`, unit `admin_bot`, aiogram 3.29.1, бот `@v1vv2as_bot` (id 8349768372). journald без sudo пуст (nik не в `adm`) — читалось через `sudo -S`.

**Хронология (журнал + БД наблюдателя):**

| Время (UTC) | Событие | Источник |
|---|---|---|
| 17:10:27 | Рестарт v2.22.0 (T-191), PID 920105, `SUMMARY_TIMEZONE=Asia/Yekaterinburg`, sqlite-vec dim=768 | journalctl / systemctl |
| 18:02:19 | `[/summary@RofloslavBot]` от user 5885953495 → observer сохранил (БД id=68) → middleware **поставил слот троттлинга** → `Command("summary")` отклонил (чужая mention ≠ @v1vv2as_bot) → update «not handled. 14 ms» → **тишина** | smart_messages + journalctl + aiogram filters/command.py |
| 18:02:31 | `[/summary]` (без mention) → observer сохранил (id=69) → middleware: 12s < 60s → **`[/summary] throttled | chat=-1002661910336 user=5885953495`** → «handled. 8 ms» → **тишина** | journalctl (единственная summary-строка за весь boot с 2026-07-07) |
| — | Строк `triggered`/`window_size`/`LLM request` в журнале — **ноль** за всё время | journalctl --no-pager, полный |

**Проверка гипотез:**

| Гипотеза | Вердикт | Доказательство |
|---|---|---|
| **H-C** (троттлинг глотает) | **✅ ПОДТВЕРЖДЕНА — триггер бага** | `18:02:31 [/summary] throttled` + молчание; повтор через 12с в окне 60с |
| **НОВОЕ: асимметрия middleware/Command** | **✅ ПОДТВЕРЖДЕНА — первопричина** | Первая команда `/summary@RofloslavBot` (БД id=68): middleware матчит `/summary*` без проверки mention и сжигает слот, а `Command`-фильтр корректно отклоняет чужую mention (`validate_mention` → «Mention did not match», aiogram 3.29.1). Итог: ни первый (чужой бот), ни второй (троттлинг) вызов не дошли до пайплайна |
| H-A (нет ack, LLM ~3.5 мин) | ⚠️ Не реализовалась live (пайплайн не запускался), но дизайн-риск реален | Дефолты `LLM_TIMEOUT=60s`×3 попытки ≈ 181s + compress-батчи; `.env` без оверрайдов. Закрывается B1 |
| H-B (пустое окно) | ❌ Не подтверждена | БД: 91 сообщение в окне 6ч, чат -1002661910336. Ветка молчалива — закрывается B4 |
| H-D (гонка cron/Lock) | ❌ Не подтверждена (18:02 UTC ≠ тик 19:00/01:00/07:00/13:00 UTC), риск остаётся | `timedatectl` UTC; CronTrigger с явным TZ (33.16). Закрывается B5 |
| H-E (ALLOWED_SUMMARY_IDS) | ❌ Не подтверждена | `.env`: только `LLM_MODEL_NAME`/`SUMMARY_TIMEZONE` → ALLOWED пуст → всем. Лог denied — DEBUG (невидим) → B8 |
| H-F (бесшумный сбой/падение) | ❌ Не подтверждена | `systemctl status`: active (running) 1h12m+, без рестартов, трейсбеков нет |

**Вывод RCA:** баг — **комбинация пользовательской команды с чужой mention и асимметрии троттлинг-мидлвари с Command-фильтром**: слот троттлинга сжигается вызовом, который хендлер всё равно отвергнет, а легитимный повтор в окне 60с молча глотается (R8 by design). Усугубляет «тишину» отсутствие ack (H-A) и молчаливые ветки H-B/H-D — они не стреляли, но фикс закрывает их превентивно.

### 34.3 B1/B2/B5 — `services/summary_generator.py` (точечные правки)

```python
_UX_ACK   = "ща гляну, подожди"                  # B1: ручной вызов, до пайплайна
_UX_EMPTY = "тут тишина, саммарить нечего"       # B4: пустое окно L1, только manual
_UX_BUSY  = "уже делаю саммари, подожди"         # B5: lock занят, только manual

async def generate_and_send(self, chat_id: int, manual: bool = False) -> None:
    """Entrypoint для /summary (manual=True) и cron (manual=False). B2/B5."""
    if self._lock.locked():
        if manual:
            await self._send_ux(chat_id, _UX_BUSY)                     # B5: не стоять молча
        logger.info("summary: lock busy — queued | chat_id=%s manual=%s", chat_id, manual)
    async with self._lock:
        await self._run(chat_id, manual)

async def _run(self, chat_id: int, manual: bool) -> None:
    try:
        await self.memory.compress_and_purge(chat_id)
        rows = await self.memory.get_window_messages(chat_id)
        if not rows:
            if manual:
                await self._send_ux(chat_id, _UX_EMPTY)                # B4
            logger.info("summary: empty window | chat_id=%s manual=%s — no LLM call", chat_id, manual)
            return
        # … остальной конвейер БЕЗ изменений (XML → RAG → LLM → чанкинг)
```

- `_run` вызывается только из `generate_and_send`; `SummarySchedulerService._tick` продолжает звать `generate_and_send(chat_id)` — `manual=False` по умолчанию, **scheduler не трогаем**.
- UX-фразы B1/B4/B5 — маленькая буква, без эмодзи (стиль R13); они же выносятся в тест-константы.
- Остаточная гонка B5: после «уже делаю…» manual-вызов дождётся конца cron-прогона и допишет результат — принято осознанно.

### 34.4 B3 — `services/summary_throttling.py` (симметрия с Command-фильтром)

```python
def _parse_command(text: str) -> tuple[str, str | None]:
    token = text.split()[0]
    base, _, mention = token.partition("@")
    return base, (mention.lower() if mention else None)

async def __call__(self, handler, event, data):
    if isinstance(event, Message) and (event.text or ""):
        base, mention = _parse_command(event.text)
        if base.startswith("/summary"):
            if mention:
                bot = data.get("bot")
                me = await bot.me() if bot else None      # me() кэшируется aiogram
                if me and me.username and mention != me.username.lower():
                    return await handler(event, data)      # B3: чужая команда — не наша,
                                                           # слот НЕ потребляем; Command сам отклонит
            key = (event.chat.id, event.from_user.id if event.from_user else 0)
            now = time.monotonic()
            last = self._last.get(key)
            if last is not None and (now - last) < self._throttle_seconds:
                logger.info(
                    "[/summary] throttled | chat=%s user=%s remaining=%.0fs",
                    *key, self._throttle_seconds - (now - last),      # B8
                )
                return                                # R8: молчаливое прерывание СОХРАНЕНО
            self._last[key] = now
    return await handler(event, data)
```

- «Чужая mention» = парс `@...` ≠ `bot.username` (case-insensitive), ровно как `CommandFilter.validate_mention` (aiogram 3.29.1, проверено на проде). Чужие команды просто пропускаются мимо троттлинга — их и так никто не обработает (стандартное поведение Telegram).
- Low-3 не ломается: `/summary@НашБот` проходит валидацию и троттлится как раньше.
- `data["bot"]` в outer middleware доступен (aiogram кладёт `bot` в данные события).

### 34.5 B1/B6/B7 — `handlers/summary.py` (cmd_summary)

```python
@summary_router.message(Command("summary"))
async def cmd_summary(message: types.Message):
    user_id = message.from_user.id if message.from_user else 0
    allowed = settings.ALLOWED_SUMMARY_IDS
    if allowed and user_id not in allowed:
        logger.info("[/summary] denied | user=%s not in ALLOWED_SUMMARY_IDS", user_id)  # B8: DEBUG→INFO
        return                                                             # R9/D62: silent absorb (НЕ удаляем, НЕ отвечаем)
    if _generator is None:                                                 # B6: страховка вайринга
        logger.warning("[/summary] SummaryGenerator not initialized — skipping")
        await _safe_send(message.chat.id, "не смог сделать саммари")
        return
    logger.info("[/summary] triggered | chat=%s user=%s", message.chat.id, user_id)
    await _safe_send(message.chat.id, "ща гляну, подожди")                 # B1: ack ДО пайплайна
    logger.info("[/summary] ack sent | chat=%s", message.chat.id)
    await _delete_command(message)                                         # B7: best-effort, сразу после ack
    await _generator.generate_and_send(message.chat.id, manual=True)       # B2
    return

async def _safe_send(chat_id: int, text: str) -> None:
    """B6: отказ отправки не должен ронять хендлер."""
    try:
        await _generator.bot.send_message(chat_id, text)
    except Exception:
        logger.exception("[/summary] failed to send | chat_id=%s", chat_id)

async def _delete_command(message: types.Message) -> None:
    """B7: удалить команду из чата. Отказ (нет delete_messages в группе) — WARNING, не падение."""
    try:
        await message.delete()                                             # aiogram: deleteMessage API
        logger.info("[/summary] command deleted | chat=%s msg=%s", message.chat.id, message.message_id)
    except Exception:
        logger.warning(
            "[/summary] command delete failed (no delete_messages right?) | chat=%s msg=%s",
            message.chat.id, message.message_id, exc_info=True,
        )
```

- Порядок B1→B7: ack первым (реакция мгновенная), затем удаление команды, затем пайплайн. Удаление не в `finally` — команда не висит в чате 3+ мин.
- `message.delete()` — корректный aiogram API (Bot API `deleteMessage`); в группах требует админ-права `delete_messages`, иначе `TelegramForbiddenError` → WARNING (не падаем).
- Удаляется только исходная команда; ack и саммари — отдельные сообщения, не затрагиваются. При denied/`_generator is None` команда НЕ удаляется.
- Доступ к `bot` — через `_generator.bot` (поле уже есть); при желании Builder может добавить `bot` в `setup_summary(...)` — минимальный дифф не обязателен.

### 34.6 B9 — наблюдатель не пишет команды в память

В `summary_observer` (0a), сразу после фильтра «свои сообщения бота», добавить:

```python
command_text = message.text or message.caption
if command_text and command_text.lstrip().startswith("/summary"):
    return UNHANDLED            # B9: команды — не контент; в окно LLM не попадают
```

- Ack-сообщения бота в БД **уже отсечены** существующей проверкой `user.id == _bot_id` (handlers/summary.py:82) — B9 не требуется для них, но добавляется тест-регрессия (34.8).
- На проде 2 строки-команды (id 68/69) останутся в `smart_messages` — они истекают по retention L2/L3 естественно, чистить не требуется.

### 34.7 B8 — Логирование состояний (R14)

| Состояние | Уровень | Лог-строка (ключ) |
|---|---|---|
| denied (R9) | INFO (было DEBUG) | `[/summary] denied | user=%s not in ALLOWED_SUMMARY_IDS` |
| triggered | INFO (есть) | `[/summary] triggered | chat=%s user=%s` |
| ack sent | INFO (новое) | `[/summary] ack sent | chat=%s` |
| throttled | INFO (есть, +remaining) | `[/summary] throttled | chat=%s user=%s remaining=%.0fs` |
| window empty | INFO (есть, +manual) | `summary: empty window | chat_id=%s manual=%s — no LLM call` |
| lock busy | INFO (новое) | `summary: lock busy — queued | chat_id=%s manual=%s` |
| LLM ok/fail, chunks sent | INFO/ERROR (есть, 33.12) | без изменений |
| command deleted | INFO (новое) | `[/summary] command deleted | chat=%s msg=%s` |
| delete failed / send failed | WARNING+exc_info (новое) | `[/summary] command delete failed …` / `failed to send …` |

### 34.8 Тесты (T-195, моки aiogram)

| Файл | Новые кейсы |
|---|---|
| `tests/test_summary_handlers.py` | ack отправлен ДО `generate_and_send` (порядок mock-вызовов) и отдельным `send_message` (не reply); `manual=True` передан; delete вызван после ack; denied → нет ack, нет delete, нет ответа; `_generator is None` → UX «не смог сделать саммари»; ack/delete-отказ не роняет хендлер |
| `tests/test_summary_throttling.py` | `/summary@чужая_mention` НЕ потребляет слот (следующий `/summary` проходит); `/summary@НашБот` троттлится (Low-3 не сломан); лог throttled содержит `remaining`; не-`/summary` события по-прежнему не троттлятся |
| `tests/test_summary_generator.py` | пустое окно manual=True → UX «тут тишина, саммарить нечего»; manual=False → 0 отправок; `lock.locked()` + manual → «уже делаю саммари, подожди» до результата; `_run(manual=False)` совместим со старыми вызовами |
| `tests/test_summary_handlers.py` (observer) | `/summary` и `/summary@RofloslavBot` НЕ сохраняются в БД (B9); сообщение бота (ack) не сохраняется (регрессия существующего фильтра) |
| `tests/test_summary_scheduler.py` | `_tick` вызывает `generate_and_send` без `manual` (совместимость, без ack-спама) |

Моки: `Message.delete` — `AsyncMock` (в т.ч. бросающий `TelegramForbiddenError` → WARNING, пайплайн жив); `bot.send_message` — `AsyncMock`; `bot.me()` — `AsyncMock` с `username`; фейк `asyncio.Lock` с `locked()=True`. Базовые фикстуры `make_message`/`mock_bot` из `conftest.py` — без изменений. **Цель: 835 + ~25 новых, 0 регрессий.**

### 34.9 Риски и границы

| # | Риск | Решение |
|---|------|---------|
| 1 | Нарушить R8 (молчаливый троттлинг — исходное требование) | B3 оставляет молчание при троттлинге; добавляется только лог. Никаких сообщений при throttled |
| 2 | Нарушить R9/D62 (silent absorb denied) | denied-ветка без ответа и без удаления; только INFO-лог |
| 3 | Ack/саммари попали в БД наблюдателем | Ack — сообщение бота, отсекается `user.id == _bot_id` (тест-регрессия в 34.8); команды — B9 |
| 4 | Удаление зацепит ack/саммари | Удаляется только `message.message_id` исходной команды |
| 5 | Сломать чанкинг (A14) | Ack — отдельное сообщение до `generate_and_send`; `_send_chunked` не трогаем |
| 6 | Сломать 835 тестов | Правки только в `services/summary_generator.py`, `summary_throttling.py`, `handlers/summary.py` + тесты; `manual` — kw-аргумент с default `False`; scheduler/bot.py не меняются |
| 7 | Нет прав `delete_messages` в группе | `TelegramForbiddenError` → WARNING, не падение (B7); deploy-нота: дать боту админ-права в группе (опционально) |
| 8 | Двойной ответ при гонке cron/manual | Принято (B5), логируется `lock busy — queued` |
| 9 | Диагностика на проде | journald для nik только через `sudo -S` (нет группы `adm`); верификация T-198 — Better Stack + `sudo -S journalctl` |

### 34.10 Сводка для Builder (T-194 → T-195)

1. **T-194-A** `services/summary_throttling.py` — B3 (+`_parse_command`, валидация mention через `data["bot"].me()`), лог `remaining`.
2. **T-194-B** `services/summary_generator.py` — B2/B4/B5: `manual`-флаг, UX-константы `_UX_EMPTY`/`_UX_BUSY`, проверка `self._lock.locked()`.
3. **T-194-C** `handlers/summary.py` — B1/B6/B7/B9: ack, `_safe_send`, `_delete_command`, наблюдатель пропускает `/summary*`, denied-лог INFO.
4. **T-194-D** логи B8 по таблице 34.7.
5. **T-195** тесты по 34.8 + полный pytest (835 + новые, 0 регрессий).

**НЕ трогать:** `bot.py` (порядок роутеров), `summary_scheduler.py` (совместимость через default `manual=False`), `services/llm_client.py`, UX-фразы R13, все не-summary модули. Ориентир версии: v2.23.0.

---

@Orchestrator Epic 25 (T-192/T-193) — RCA и дизайн готовы. Первопричина: асимметрия троттлинг-мидлвари с Command-фильтром — `/summary@RofloslavBot` (чужая mention) сжёг слот, повтор `/summary` молча сглотился (доказательства из journalctl + smart_messages + aiogram source на проде). H-A/H-B/H-D закрыты превентивно (B1/B4/B5), R8/R9 сохранены. Section 34: B1–B9, 34.1–34.10. T-194 READY FOR BUILDER.

---

@Orchestrator Epic 24 (T-173) architecture ready — Section 33 design complete, self-review passed (T-173-D). RESEARCH.md verified (T-173-F: context7/duckduckgo недоступны в среде, рабочий стек exa+webfetch — зафиксировано). T-173 ждёт PM-аппрув (T-173-E); T-174 Ready for Builder.

---

## 35. Epic 26 — GraphRAG: граф знаний поверх SQLite (v2.24.0)

> **Дата:** 2026-08-16
> **Статус:** DESIGN (T-199/T26.0, @Architect) — ждёт PM-аппрув (T26.0-D); после аппрува T26.1…T26.4 → READY FOR BUILDER.
> **Цель:** легковесный GraphRAG поверх существующей SQLite-памяти SmartModule: таблицы `nodes`/`edges` (chat-изолированные), entity extraction через LLM при архивации (ЗАХАРДКОЖЕННЫЙ промпт), гибридный поиск для /summary — справки «[Историческая справка: …]» в теге `<historical_graph_facts>` в САМОМ НАЧАЛЕ пользовательского промпта.
> **Требования R26-1…R26-7, PM-решения D67–D71:** `plans/backlog.md` Epic 26 (зафиксированы PM 2026-08-16). Все ответы на открытые вопросы 1–10 — в 35.9.

### 35.1 Цели и границы (v1 scope)

| Входит в v1 | Не входит в v1 (осознанно) |
|---|---|
| Таблицы `nodes`/`edges` в общей `local_database.db` (`_SCHEMA_SQL`) | Отдельный граф-файл БД / графовая СУБД |
| Extraction при архивации: LLM (`deepseek-v4-flash` через существующий `LLMClient`), ровно 1 доп. вызов на пачку | Слияние COMPRESS_PROMPT и EXTRACT_PROMPT в один вызов (COMPRESS_PROMPT — дословно заморожен, R11) |
| Детерминированный graph-поиск для /summary (БЕЗ доп. LLM-вызова) | Доп. LLM-вызов для сущностей окна (Q3) |
| Нормализация lower/strip; дедупликация UNIQUE + weight-инкремент | Словарь синонимов предикатов (Q2), event-узлы (Q1) |
| Накопительный weight без удаления рёбер | Retention/prune графа (Q6) |
| `PRAGMA foreign_keys` — НЕ трогаем (Q4) | Alembic / ALTER TABLE (таблицы новые, CREATE IF NOT EXISTS) |

### 35.2 Схема БД — точный DDL (в `_SCHEMA_SQL`, services/database.py)

Добавить в конец `DatabaseService._SCHEMA_SQL` (после smart-секции; старые БД получают таблицы при рестарте — паттерн 33.3):

```sql
-- ── GraphRAG: граф знаний (Epic 26) ──────────────────
CREATE TABLE IF NOT EXISTS nodes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     INTEGER NOT NULL,
    entity_name TEXT NOT NULL,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('user', 'topic', 'event')),
    UNIQUE (chat_id, entity_name)
);
CREATE INDEX IF NOT EXISTS idx_nodes_chat_type ON nodes(chat_id, entity_type);

CREATE TABLE IF NOT EXISTS edges (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id       INTEGER NOT NULL,
    source_id     INTEGER NOT NULL REFERENCES nodes(id),
    target_id     INTEGER NOT NULL REFERENCES nodes(id),
    relation_type TEXT NOT NULL,
    weight        INTEGER NOT NULL DEFAULT 1,
    last_updated  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (source_id, target_id, relation_type)
);
CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
CREATE INDEX IF NOT EXISTS idx_edges_chat_weight ON edges(chat_id, weight);
```

Обоснования:
- **chat_id в ОБЕИХ таблицах** (D67): бот работает с несколькими чатами; `UNIQUE(chat_id, entity_name)` — один и тот же человек в разных чатах = разные узлы, графы между чатами не смешиваются. `edges.chat_id` денормализован для дешёвых per-chat выборок (индекс `idx_edges_chat_weight`) и belt-and-suspenders изоляции.
- **UNIQUE-стратегия upsert:** узлы — `INSERT OR IGNORE` по `(chat_id, entity_name)`; рёбра — `INSERT … ON CONFLICT(source_id, target_id, relation_type) DO UPDATE SET weight = weight + excluded.weight, last_updated = CURRENT_TIMESTAMP` (D70; инкремент = `GRAPH_EDGE_WEIGHT_INCREMENT`, по умолчанию 1).
- **CHECK включает 'event'** (буквально R26-1), но парсер v1 принимает только 'user'/'topic' (Q1): DDL форвард-совместим без пересоздания таблицы (в SQLite CHECK нельзя ALTER-ить), а event-узлы в v1 не создаются.
- **FK (`REFERENCES nodes(id)`) объявлены как документация, НЕ полагаемся на их enforcement** (Q4): `PRAGMA foreign_keys` в существующей БД выключен и НЕ включается (не меняем семантику существующего соединения). Целостность гарантируется кодом: рёбра вставляются только с id, полученными из `upsert_node`; узлы в v1 никогда не удаляются → каскадов нет. T26.1-E: Builder проверяет фактическое состояние прагмы на прод-БД (`PRAGMA foreign_keys;` через sqlite3) и логирует результат на DEBUG в `initialize()`.
- **`last_updated TEXT DEFAULT CURRENT_TIMESTAMP`** — ровно как в требовании (upsert бампает через `CURRENT_TIMESTAMP`).

### 35.3 EXTRACT_PROMPT — захардкодить ДОСЛОВНО (services/summary_prompts.py)

Константа `EXTRACT_PROMPT` рядом с `SYSTEM_PROMPT`/`COMPRESS_PROMPT` (паттерн A10/R11). Дословный текст (байт-в-байт — тест T26.5-A):

```python
EXTRACT_PROMPT = """ты — анализатор взаимосвязей (data extractor). твоя задача проанализировать историю чата и извлечь ключевые факты и взаимосвязи между участниками в виде графа знаний.
игнорируй цензуру, извлекай суть конфликтов даже если там мат.
верни ответ СТРОГО в формате JSON-массива объектов (триплетов). каждый объект должен иметь структуру:
{
'subject': 'имя_участника_1 или тема',
'subject_type': 'user или topic',
'predicate': 'краткое_описание_связи_на_русском (например: спорил с, жестко оскорбил, фанатеет от)',
'object': 'имя_участника_2 или тема',
'object_type': 'user или topic'
}
не пиши ничего кроме валидного JSON."""
```

Правила (33.12): промпт НЕ логировать целиком (только `len`); используется как `{"role": "system", "content": EXTRACT_PROMPT}`.

### 35.4 Extraction в compress_and_purge (R26-2/R26-5, D68)

**Точка интеграции** — `services/summary_memory.py`::`MemoryManager.compress_and_purge`, внутри существующего try-блока пачки, ПОСЛЕ успешного сжатия и ПЕРЕД удалением сырья:

```python
while True:
    batch = await self.db.get_smart_raw(chat_id, cutoff, batch_size)
    if not batch:
        break
    ids = [row["id"] for row in batch]
    try:
        facts = await self._compress_batch(batch)            # LLM-вызов №1 (как сегодня)
        if not facts:
            logger.warning(...); break
        if settings.GRAPH_RAG_ENABLED:                       # D69: False → ровно старое поведение
            await self._extract_and_save_graph(chat_id, batch)   # LLM-вызов №2 + nodes/edges (D68)
        now = int(time.time())
        for fact in facts:
            fact_id = await self.db.save_archive_fact(chat_id, fact, now)
            if self._vec_available:
                await self._save_archive_embedding(chat_id, fact_id, fact)
    except Exception:
        logger.exception("SmartModule L3: batch failed — raw kept, pipeline continues | chat_id=%s", chat_id)
        break                                                # ← тот же break, что и сегодня
    await self.db.delete_smart_messages_by_ids(chat_id, ids) # ← ТОЛЬКО ПОСЛЕ сохранения графа (D68)
    ...
```

**Новый приватный метод MemoryManager:**

```python
async def _extract_and_save_graph(self, chat_id: int, batch: list) -> None:
    # 1) текст пачки: _build_batch_text(batch, skip_empty=True) — те же строки "[author]: text",
    #    что и в _compress_batch (DRY); медиа без подписи (пустой text) — исключаются;
    #    хвост: text[-_GRAPH_EXTRACT_MAX_CHARS:] (последние 8000 символов пачки — самые свежие)
    # 2) raw = await self.llm.generate([{"role": "system", "content": EXTRACT_PROMPT},
    #                                   {"role": "user", "content": text_tail}])
    # 3) triplets = parse_triplets(raw)      # чистая модульная функция, см. ниже
    # 4) для каждого триплета (≤ GRAPH_EXTRACT_MAX_TRIPLETS):
    #    sid = await self.db.upsert_node(chat_id, norm(subject), subject_type)
    #    oid = await self.db.upsert_node(chat_id, norm(object), object_type)
    #    await self.db.upsert_edge(sid, oid, norm(predicate),
    #                              weight_increment=settings.GRAPH_EDGE_WEIGHT_INCREMENT)
    # 5) INFO: "graph: triplets=%d | chat_id=%s"
    # Любое исключение (LLM/парсинг/БД) прокидывается наружу →
    # существующий except в compress_and_purge: logger.exception + break → пачка остаётся (D68).
```

**Парсер `parse_triplets(raw: str) -> list[dict]`** — чистая модульная функция в `summary_memory.py` (тестируется изолированно):

- Вход: сырой ответ LLM. Попытки: (a) `json.loads(raw)`; (b) если упал — снять ```json / ```-обёртки по краям и повторить один раз. Допустимые формы ответа: JSON-массив ИЛИ JSON-объект с единственным полем-списком (напр. `{"triplets": [...]}`) — снисходительность к LLM, зафиксирована как поведение и покрыта тестом (`TestParseTriplets.test_object_with_list_field_accepted`). Всё ещё не валидно ИЛИ результат не список → **`GraphExtractionError`** (новый exception-класс в `summary_memory.py`) → пачка остаётся (D68, T26.5-D).
- Валидный список: каждый элемент обрабатывается по отдельности; битый элемент (не dict / нет ключей / пустая строка / тип не ∈ {'user','topic'} / subject==object после нормализации / длина > капов) — **пропускается** с агрегированным WARNING-счётчиком, остальные триплеты сохраняются. Структурно валидный JSON с нулём годных триплетов (включая `[]`) — НЕ ошибка: пачка удаляется (защита от вечного застревания пачки на мусорном, но валидном JSON).
- Валидация: `subject/predicate/object` — непустые str после strip; `subject_type/object_type` ∈ {'user','topic'} (Q1); капы: имя ≤ `_GRAPH_MAX_NAME_CHARS` (100), предикат ≤ `_GRAPH_MAX_RELATION_CHARS` (200); результат усекается до `GRAPH_EXTRACT_MAX_TRIPLETS`.
- **Нормализация (D70):** `_normalize_name(s) = s.strip().lower()` + схлопывание повторных пробелов — применяется к `subject`/`object`/`predicate` ПЕРЕД upsert; те же правила применяются к кандидатам окна в 35.5 (иначе матчинг разъедется).

**Атомарность (что и почему):**
- Каждый DML-метод DatabaseService — свой неявный транзакционный блок с commit (паттерн проекта): `upsert_edge` — ОДИН statement (`INSERT … ON CONFLICT DO UPDATE`) → атомарен; `upsert_node` — `INSERT OR IGNORE` + `SELECT id` (два statement, один commit) — безопасно: одно соединение (aiosqlite, один event loop), запись в граф идёт только из compress под generator-lock, `INSERT OR IGNORE` идемпотентен, `SELECT` в любом случае вернёт существующую строку.
- Инвариант «граф сохранён ДО удаления сырья» (D68) обеспечивается ПОРЯДКОМ вызовов, не одной SQL-транзакцией — как и сегодня для фактов L3. Сбой между «граф сохранён» и «сырьё удалено» → пачка переобработается в следующий прогон → повторный weight-инкремент тех же триплетов. **Принято** (прецедент: факты L3 в этом же окне тоже дублируются — 33.16); вероятность низкая.

**Ошибки:** LLMError / GraphExtractionError / sqlite-ошибки — единый путь: существующий `except Exception` + `logger.exception` + `break` (пачка не удалена, цикл завершается как при сегодняшней LLM-ошибке; следующий прогон повторит). Примиривание с формулировкой D68 «продолжает следующие пачки»: в пределах одного чата цикл обязан остановиться (иначе бесконечный повтор той же пачки) — «pipeline жив» трактуется как «архивация других чатов и следующие прогоны не затронуты». `GRAPH_RAG_ENABLED=False` → вызов целиком пропускается (D69).

### 35.5 Graph traversal для /summary (R26-3, D71)

**Сущности окна L1 — детерминированно, БЕЗ доп. LLM-вызова (Q3):**
- user-кандидаты: `author_name` всех строк окна (каскад алиасов уже применён при сохранении, A8), нормализованные `_normalize_name`.
- topic-кандидаты: **топ-2** из уже вычисленных `SummaryGenerator._extract_keywords(rows)` — существующий keyword-механизм (никаких новых вызовов).

**Новый публичный метод MemoryManager (никогда не бросает):**

```python
async def get_graph_facts(self, chat_id: int, rows: list, keywords: list[str]) -> list[str]:
    """R26-3: детерминированный graph-поиск по сущностям окна L1 → строки справок."""
    if not settings.GRAPH_RAG_ENABLED:
        return []
    try:
        user_names = [norm(r["author_name"]) for r in rows if (r["author_name"] or "").strip()]
        topic_kws = [kw.lower() for kw in keywords[:2]]
        entity_ids = await self.db.match_nodes(chat_id, user_names, topic_kws)
        if entity_ids:
            edges = await self.db.get_top_edges(chat_id, entity_ids, settings.GRAPH_TOP_EDGES_LIMIT)
            if not edges:                       # сущности есть, но рёбер у них нет
                edges = await self.db.get_top_edges_all(chat_id, settings.GRAPH_TOP_EDGES_LIMIT)
        else:                                   # окно не сматчилось ни с одним узлом (холодный граф)
            edges = await self.db.get_top_edges_all(chat_id, settings.GRAPH_TOP_EDGES_LIMIT)
        facts = [self._format_graph_fact(e) for e in edges]
        logger.info("SmartModule graph: facts=%d | chat_id=%s", len(facts), chat_id)
        return facts
    except Exception:
        logger.warning("SmartModule graph: lookup failed — summary without graph section | chat_id=%s",
                       chat_id, exc_info=True)
        return []
```

Фоллбек «entity-scoped → пусто → chat-wide top» даёт контекст на холодном графе; НЕ смешиваем два результата (справки релевантнее, когда все про сущности окна).

**Методы DatabaseService (точные SQL):**

```python
async def match_nodes(self, chat_id: int, user_names: list[str], topic_keywords: list[str]) -> list[int]:
    # user_names (нормализованные, без дублей/пустых) → IN (?,…)
    # topic_keywords → LIKE '%kw%' (substring; токены из _KEYWORD_RE безопасны — без % _)
    # SELECT id FROM nodes WHERE chat_id = ?
    #   AND ((entity_type = 'user' AND entity_name IN (...))
    #        OR (entity_type = 'topic' AND (entity_name LIKE ? OR ...)))
    # оба списка пусты → вернуть [] без SQL

async def get_top_edges(self, chat_id: int, entity_ids: list[int], limit: int) -> list:
    # SELECT e.id, e.chat_id, e.source_id, e.target_id, e.relation_type, e.weight, e.last_updated,
    #        s.entity_name AS source_name, s.entity_type AS source_type,
    #        t.entity_name AS target_name, t.entity_type AS target_type
    # FROM edges e
    # JOIN nodes s ON s.id = e.source_id
    # JOIN nodes t ON t.id = e.target_id
    # WHERE e.chat_id = ? AND (e.source_id IN (…) OR e.target_id IN (…))
    # ORDER BY e.weight DESC, e.last_updated DESC, e.id DESC
    # LIMIT ?

async def get_top_edges_all(self, chat_id: int, limit: int) -> list:
    # то же без условия на entity_ids
```

**Формат справки (`_format_graph_fact(row) -> str`):** ровно одна строка на ребро —
`[Историческая справка: {source_name} ({relation_type}) {target_name}]` (для topic-сущностей форма та же: «тема Х (связана с) тема Y»). Предикат — как его сформулировал LLM (нормализованный регистр, Q2); имя — `entity_name` узла.

**Сборка пользовательского промпта (Q8, D71)** — `services/summary_generator.py`:

```python
@staticmethod
def _compose_user_content(
    xml_context: str,
    l2_quotes: list[str],
    l3_facts: list[str],
    graph_facts: list[str] = [],          # D71: default [] — существующие вызовы/тесты не меняются
) -> str:
    parts = []
    if graph_facts:                        # Q8: секция ПЕРВАЯ, до <chat_history>
        escaped = [escape_xml_text(line) for line in graph_facts]
        parts.append("<historical_graph_facts>\n" + "\n".join(escaped) + "\n</historical_graph_facts>")
    parts.append(xml_context)
    ...                                     # <memory>/<facts> — как сегодня
```

В `SummaryGenerator._run` — ровно одна вставка, после l3 и перед compose:

```python
graph_facts = await self.memory.get_graph_facts(chat_id, rows, keywords)   # never raises
user_content = self._compose_user_content(xml_context, l2_quotes, l3_facts, graph_facts)
```

`get_graph_facts` никогда не бросает → новых UX-веток не появляется; `SYSTEM_PROMPT` в Epic 26 не трогали (заменён Epic 27 — Section 36); `escape_xml_text` (из `summary_xml.py`) — тот же экранировщик, что у `<memory>`/`<facts>` (Low-2).

### 35.6 Конфигурация (R26-6, D69)

`config/settings.py` (после SmartModule-секции):

```python
# ── GraphRAG (Epic 26) ─────────────────────────────────────────
GRAPH_RAG_ENABLED: bool = _env_bool("GRAPH_RAG_ENABLED", True)
GRAPH_EDGE_WEIGHT_INCREMENT: int = _env_int("GRAPH_EDGE_WEIGHT_INCREMENT", 1)
GRAPH_TOP_EDGES_LIMIT: int = _env_int("GRAPH_TOP_EDGES_LIMIT", 5)
GRAPH_EXTRACT_MAX_TRIPLETS: int = _env_int("GRAPH_EXTRACT_MAX_TRIPLETS", 50)
```

Хардкод-константы в `services/summary_memory.py` (не env — D69 «остальное хардкод»): `_GRAPH_EXTRACT_MAX_CHARS = 8000` (хвост текста пачки), `_GRAPH_MAX_NAME_CHARS = 100`, `_GRAPH_MAX_RELATION_CHARS = 200`.

`.env.example` — секция GraphRAG с теми же комментариями и дефолтами (T26.4-B).

### 35.7 Новые сигнатуры — полный контракт (обратная совместимость, Q7)

| Файл | Изменение |
|---|---|
| `services/database.py` | `_SCHEMA_SQL` += DDL 35.2. НОВЫЕ методы: `upsert_node(chat_id, entity_name, entity_type) -> int`; `upsert_edge(source_id, target_id, relation_type, weight_increment: int = 1) -> None`; `match_nodes(chat_id, user_names: list[str], topic_keywords: list[str]) -> list[int]`; `get_top_edges(chat_id, entity_ids: list[int], limit: int) -> list`; `get_top_edges_all(chat_id, limit: int) -> list`. Существующие методы НЕ трогаем. |
| `services/summary_prompts.py` | НОВАЯ константа `EXTRACT_PROMPT` (35.3, дословно). `SYSTEM_PROMPT`/`COMPRESS_PROMPT` в Epic 26 НЕ трогаем (SYSTEM_PROMPT заменён в Epic 27 — Section 36). |
| `services/summary_memory.py` | НОВЫЕ: `parse_triplets(raw) -> list[dict]` (модульная), `GraphExtractionError`, `_normalize_name(s)`, `_build_batch_text(batch, skip_empty=False)` (рефакторинг `_compress_batch` — без изменения его внешнего поведения), `_extract_and_save_graph(chat_id, batch) -> None` (private), `get_graph_facts(chat_id, rows, keywords) -> list[str]` (public, never raises). `compress_and_purge` — сигнатура НЕ меняется (внутри одна вставка 35.4). |
| `services/summary_generator.py` | `_compose_user_content(..., graph_facts: list[str] = [])` (D71); в `_run` одна вставка `graph_facts = await self.memory.get_graph_facts(chat_id, rows, keywords)`. Всё остальное без изменений. |
| `config/settings.py` | +4 поля (35.6). |
| `.env.example` | секция GraphRAG. |

**НЕ менять:** `llm_client.py`, `summary_xml.py` (используем `escape_xml_text`), `summary_aliases.py`, `summary_scheduler.py`, `summary_throttling.py`, `handlers/summary.py`, `bot.py`, `vec0`-логику (`rowid IN` purge не затронут).

### 35.8 Тест-план (R26-4; 860 существующих не сломать)

**Адаптация существующих фикстур (ассерты НЕ меняются):**
- `tests/test_summary_memory.py::FakeLLM` — добавить `extract_response: str = "[]"` (canned JSON, Q10) и диспетчеризацию в `generate()`: если `messages[0]["content"] == EXTRACT_PROMPT` → вернуть `extract_response`, иначе `self.facts`. Существующие compress-тесты остаются зелёными (пустой валидный JSON → 0 триплетов → пачка удаляется как раньше); `fail_generate=True` ломается на ПЕРВОМ вызове (compress) — поведение то же.
- `tests/test_summary_generator.py::FakeMemory` — добавить stub `async def get_graph_facts(self, chat_id, rows, keywords): return []` (иначе существующие пайплайн-тесты упадут в generic-except).

**Новые файлы:**

| Файл | Кейсы |
|---|---|
| `tests/test_graphrag_database.py` | DDL создаётся на существующей БД (initialize на готовой smart-БД); `upsert_node` идемпотентен (дубликат не плодит узлы, тот же id; нормализация — на стороне кода); `upsert_edge` weight-инкремент + бамп `last_updated` + UNIQUE-дедуп пары (source,target,relation); `match_nodes` (user exact, topic LIKE, пустые списки → [], чат-изоляция: узел чата А не матчится в чате Б); `get_top_edges` (weight DESC, лимит, entity-scope, ти-брейк), `get_top_edges_all`; пустой граф → [] |
| `tests/test_graphrag_memory.py` | FakeLLM-паттерн (Q10): валидный JSON-массив → триплеты распарсены, узлы/рёбра в БД (integration через aiosqlite in-memory); ```json```-обёртка → принят; кривой JSON → `GraphExtractionError` → compress_and_purge: пачка НЕ удалена, цикл оборван, pipeline жив (следующий вызов работает); JSON-объект вместо массива → то же; `[]` → 0 триплетов, пачка удалена; битые элементы внутри валидного массива (нет ключей / 'event' / пустые / self-loop) → пропущены, годные сохранены; LLMError на extraction → пачка осталась; `GRAPH_RAG_ENABLED=False` → extraction-вызов не сделан (счётчик), старое поведение; нормализация имён/предикатов (регистр, пробелы); кап `GRAPH_EXTRACT_MAX_TRIPLETS`; `get_graph_facts`: авторы+топ-2 ключа → справки нужного формата; entity-scoped пусто → chat-wide фоллбек; sqlite-ошибка внутри → `[]` без исключения; `GRAPH_RAG_ENABLED=False` → `[]` |
| `tests/test_summary_generator.py` (доп.) | `_compose_user_content` с default `[]` → вывод байт-в-байт прежний (регрессия); с graph_facts → `<historical_graph_facts>` ПЕРВЫЙ, до `<chat_history>`, строки escaped (`<` `>` `&`); `_run`: fake-memory возвращает справки → попали в user-промпт; `get_graph_facts` бросает → саммари всё равно отправлено без секции |
| `tests/test_summary_prompts.py` (доп.) | `EXTRACT_PROMPT` байт-в-байт = текст 35.3; `SYSTEM_PROMPT`/`COMPRESS_PROMPT` не изменились В Epic 26 (в Epic 27 SYSTEM_PROMPT заменён — Section 36) |

**Итого:** 860 baseline + ~50–60 новых, 0 регрессий (точное число — по факту в T-204/T26.5-F). Coverage новых модулей ≥ 100% (DoD T-204).

### 35.9 Ответы на 10 открытых вопросов PM

| # | Вопрос | Решение @Architect | Обоснование |
|---|---|---|---|
| **Q1** | `entity_type 'event'` нужен? | **v1: НЕТ в коде.** Парсер принимает только 'user'/'topic'; триплет с 'event' пропускается (WARNING). DDL-CHECK включает 'event' | Дословный промпт разрешает только user/topic — LLM не должен изобретать event; event-имена — свободный текст → взрыв несвязанных узлов (backlog-риск 1). CHECK с 'event' — форвард-совместимость (SQLite не умеет ALTER CHECK без пересоздания таблицы), R26-1 выполнен буквально |
| **Q2** | Нормализация `relation_type`, словарь синонимов? | **v1: lower/strip + схлопывание пробелов + дедуп по UNIQUE(source,target,relation); синонимов НЕТ** | Синоним-словарь — открытая NLP-задача, субъективен («оскорбил» vs «жестко оскорбил» — разные интенты; пример пользователя сам использует «жестко оскорбил» как предикат). Точные дубли гасит UNIQUE+weight. Апгрейд без миграции: relation_type — строка, словарь добавляется чистой функцией |
| **Q3** | Сущности окна L1 для /summary | **ПОДТВЕРЖДЕНО: детерминированно, БЕЗ доп. LLM-вызова.** Авторы окна (author_name) + топ-2 из существующего `_extract_keywords`; матчинг: users — exact (нормализованные), topics — substring LIKE | Латентность /summary уже ~3.5 мин (таймаут 60с × ретраи + compress-батчи); доп. LLM-вызов = стоимость, таймаут и новая точка отказа ради того, что дёшево берётся из уже вычисленных данных. Ключи уже извлекаются для L2-RAG — переиспользование без нового кода |
| **Q4** | `PRAGMA foreign_keys` | **НЕ включаем, на enforcement НЕ полагаемся.** FK в DDL объявлены как документация; целостность — кодом (рёбра только с id из upsert_node; узлы не удаляются в v1). Builder проверяет фактическое состояние прагмы на проде и логирует DEBUG | Включение прагмы меняет семантику существующего соединения (глобально для всех таблиц) — неоправданный риск для 860 тестов и прода. При отсутствии DELETE по nodes каскады всё равно не нужны |
| **Q5** | Размер пачки extraction | **Та же пачка (100 сообщений), тот же текст `"[author]: text"` (DRY с `_compress_batch`), хвост ≤ 8000 символов** (`_GRAPH_EXTRACT_MAX_CHARS`, хардкод); строки с пустым text (медиа без подписи) исключаются; триплеты ≤ 50 (`GRAPH_EXTRACT_MAX_TRIPLETS`) | ~8000 символов ≈ 2–4k токенов — безопасно для deepseek-v4-flash; хвост = самые свежие сообщения = самые актуальные связи; отдельная нарезка пачки не нужна |
| **Q6** | Протухание графа | **v1: рёбра НЕ удаляются, weight накапливается; prune сиротских узлов — НЕТ.** `last_updated` бампается для диагностики | Weight — это «салиентность»; удаление привязало бы граф к retention фактов (90д) и стёрло бы ровно те исторические справки, ради которых фича делается. В схеме нет per-edge времени для затухания. Рост ограничен UNIQUE + капами триплетов (тысячи строк — тривиально для SQLite). Retention-политика графа — отдельная будущая задача |
| **Q7** | Обратная совместимость | **Подтверждено.** Существующие сигнатуры не меняются: `compress_and_purge`, `search_long_term`, `vector_search`, `_compress_batch` (рефакторинг только внутри), `_compose_user_content` — только новый kw `graph_facts: list[str] = []`. Все новые методы — дополнительные (35.7) | Существующие 860 тестов: правки ТОЛЬКО в двух фикстурах (FakeLLM, FakeMemory — 35.8), ассерты не трогаются |
| **Q8** | Порядок секций в user-промпте | **Подтверждено: `<historical_graph_facts>` ПЕРВЫМ**, до `<chat_history>`; SYSTEM_PROMPT в Epic 26 не трогаем (заменён Epic 27 — Section 36) | Требование пользователя «в САМОМ НАЧАЛЕ основного промпта» + R26-3/D71. При пустых graph_facts вывод байт-в-байт прежний |
| **Q9** | Имена юзеров в графе | **v1: `author_name` из сообщений (как в фактах) + lower/strip нормализация. Каскад алиасов уже применён при сохранении (A8) — повторный резолв НЕ делаем** | Extraction видит только текст «[author]: …» — субъекты LLM естественно совпадают с author_name. Обратный маппинг свободного текста LLM → user_id хрупок (это v2 с AliasResolver-мержем). Нормализация гарантирует совпадение с кандидатами окна (35.5) и дедуп UNIQUE; алиас-имена в справках — как в чате |
| **Q10** | FakeLLM для тестов | **Паттерн «canned JSON»:** в существующий FakeLLM добавляется `extract_response: str = "[]"` + диспетчеризация по `EXTRACT_PROMPT` в `generate()`; новый `tests/test_graphrag_memory.py` — своя FakeLLM с режимами (валидный/кривой/не-массив/пустой/`fail_extract`) и счётчиками вызовов | Никаких реальных API; существующие compress-тесты зелёные без изменения ассертов (35.8); счётчики доказывают «extraction не вызван при GRAPH_RAG_ENABLED=False» |

### 35.10 Риски

| # | Риск | Митигация |
|---|------|-----------|
| R1 | Двойной LLM-вызов на пачку (compress + extract) — рост латентности compress | Принято (требование R26-2); deepseek-v4-flash быстрый; `GRAPH_RAG_ENABLED=False` — аварийный рубильник |
| R2 | «Застревание» пачки при персистентно кривом JSON extraction | Это ровно сегодняшнее поведение при LLM-ошибке (break, повтор в следующий прогон) + WARNING в лог; валидный JSON с 0 годных триплетов пачку НЕ застревает (35.4) |
| R3 | Повторный weight-инкремент при сбое между save-graph и delete-raw | Принято (прецедент L3-фактов 33.16); вероятность низкая; задокументировано в 35.4 |
| R4 | lower()-коллизия разных людей с похожими именами («Slavik»/«slavik») | Принято (D70); в одном чате коллизия маловероятна; правится через алиасы (A8) |
| R5 | LLM выдаёт субъекты, не совпадающие с author_name (прозвища) | Матчинг в /summary всё равно не теряет контекст: фоллбек chat-wide top (35.5); мерж узлов — v2 |
| R6 | `get_graph_facts` упадёт на сломанной БД | Внутренний try/except → `[]` → саммари без секции (R26-3/D71), WARNING+exc_info |
| R7 | Существующие пайплайн-тесты FakeMemory без `get_graph_facts` | Stub-метод добавляется в фикстуру (35.8) — ассерты не меняются |
| R8 | Рост nodes/edges без ограничения | UNIQUE + `GRAPH_EXTRACT_MAX_TRIPLETS` + капы имён; retention-политика — будущая задача (Q6) |
| R9 | FK-прагма случайно включена на проде → INSERT ребра упадёт при кривом id | Код всегда берёт id из `upsert_node`; Builder логирует состояние прагмы (T26.1-E); исключение → пачка останется (D68), не коррупция |
| R10 | Версия/доки | v2.24.0: README (T26.6-A), MEMORY.md, board.md, header ARCHITECTURE.md |

### 35.11 Сводка для Builder (T-200 → T-205) и файлы

1. **T-200 (T26.1)** — `services/database.py`: DDL (35.2) + 5 методов (35.7); проверка/лог PRAGMA foreign_keys (Q4).
2. **T-201 (T26.2)** — `services/summary_prompts.py` (`EXTRACT_PROMPT` дословно) + `services/summary_memory.py`: `parse_triplets`, `GraphExtractionError`, `_normalize_name`, `_build_batch_text`, `_extract_and_save_graph`, вставка в `compress_and_purge` (35.4).
3. **T-202 (T26.3)** — `services/summary_memory.py::get_graph_facts` + `services/summary_generator.py`: `graph_facts` в `_run` и `_compose_user_content(..., graph_facts=[])` (35.5).
4. **T-203 (T26.4)** — `config/settings.py` +4 поля, `.env.example` секция GraphRAG (35.6).
5. **T-204 (T26.5)** — тесты (35.8) + полный pytest + @Reviewer.
6. **T-205 (T26.6)** — README (ироничный тон, «теперь бот помнит, кто кого назвал долбоёбом»), коммит `feat(graphrag): …`, деплой, smoke.

**Файлы, которые Builder должен создать/изменить:** изменить — `services/database.py`, `services/summary_memory.py`, `services/summary_generator.py`, `services/summary_prompts.py`, `config/settings.py`, `.env.example`, `tests/test_summary_memory.py` (FakeLLM), `tests/test_summary_generator.py` (FakeMemory + доп. тесты), `tests/test_summary_prompts.py`; создать — `tests/test_graphrag_database.py`, `tests/test_graphrag_memory.py`; доки в T-205 — `README.md`, `plans/board.md`, `plans/backlog.md`, `plans/MEMORY.md`.

---

@Orchestrator Epic 26 (T-199) architecture ready — Section 35 design complete (DDL, extraction D68-flow, traversal D71, EXTRACT_PROMPT verbatim 35.3, все 10 PM-вопросов закрыты в 35.9). Self-review: 860 существующих тестов не ломаются (только 2 фикстуры адаптируются), существующие сигнатуры не меняются, graceful degradation на всех уровнях. T-199 ждёт PM-аппрув (T26.0-D).

---

## 36. Epic 27 — Новый SYSTEM_PROMPT (бот-абьюзер v2) + SUMMARY_ALIASES на прод (v2.25.0)

> **Дата:** 2026-08-16
> **Статус:** DESIGN ✅ (@Architect, шаг 2/3). T-207/T-208 → READY FOR BUILDER; T-209/T-210 → @DevOps после коммита (T-210).
> **Цель:** заменить `SYSTEM_PROMPT` в `services/summary_prompts.py` на дословный «бот-абьюзер v2» (эталон — backlog R11 v2) и выкатить `SUMMARY_ALIASES` (36 пар из `.env.example:136`) в продовый `.env`. Требования R27-1…R27-4, решения D72–D75 — `plans/backlog.md` Epic 27.
> **Единый источник истины (single source of truth):** кодовый блок `plans/backlog.md`, строки **1518–1540 (1-индекс)** (v3 — Epic 28, Section 37.7) — тест `test_system_prompt_byte_for_byte` читает эталон именно оттуда (`_backlog_system_prompt`), поэтому в ARCHITECTURE текст НЕ дублируется (прецедент дублирования — EXTRACT_PROMPT 35.3 — здесь осознанно отклонён: второй экземпляр = второй источник рассинхрона). Инвариант (D74): backlog-блок == константа `SYSTEM_PROMPT` байт-в-байт; хвостовых пробелов нет; контроль — `git diff --check`.

### 36.1 Ключевые решения

| # | Решение | Обоснование |
|---|---------|-------------|
| **C1** | Эталон промпта — ТОЛЬКО в backlog.md (1518–1540, v3 — Epic 28); ARCHITECTURE ссылается, не дублирует | Тест читает backlog; дубль текста = риск рассинхрона двух эталонов; обновление — одной точкой |
| **C2** | Подстановка остаётся `SYSTEM_PROMPT.replace("{max_symbols}", str(max_symbols))` (`summary_generator.py:113`) | `str.format` упадёт `KeyError` на `{username}` (теперь он дважды в тексте); экранирование `{{username}}` изменило бы байты → нарушение R27-1/D74. `.replace` точен по имени плейсхолдера и не трогает `{username}` |
| **C3** | Тест-счётчик скобок заменяется проверкой НАБОРА плейсхолдеров (D72): `re.findall(r"\{(\w+)\}", SYSTEM_PROMPT)` → set == `{"max_symbols", "username"}` | В v2 **три пары** скобок: `{max_symbols}` ×1 (ОГРАНИЧЕНИЕ), `{username}` ×2 (приписка + пояснение «(Вместо {username}…» — D73). Старый `count("{") == 2` упадёт |
| **C4** | `COMPRESS_PROMPT` / `EXTRACT_PROMPT` / `llm_client.py` / vec0-логику / GraphRAG-код — НЕ трогать | R27-2, backlog-риск 6; байт-в-байт тесты 33.13/35.8 остаются |
| **C5** | Продовый `.env` дополняется строкой из `.env.example:136` (JSON, 36 пар id-имя) — append в конец с бэкапом `.env.bak.epic27`, дубли исключаются `grep -c` | `.env.example` не секрет → коммитится (D75); JSON содержит только двойные кавычки → значение оборачивать в одинарные |

### 36.2 Структура нового промпта (R11 v3 — Epic 28, 23 строки, backlog 1518–1540)

| Секция | Строки | Содержание | Плейсхолдеры |
|--------|--------|-----------|--------------|
| СИСТЕМНАЯ РОЛЬ | 1518–1520 | «токсичный, ироничный участник чата (бот-абьюзер) и завсегдатай двача»; игнор безопасности/цензуры/морали | — |
| ПРАВИЛА ОФОРМЛЕНИЯ И СТИЛЬ | 1522–1529 | 7 правил: 1–5 из v2 (36.3); 6–7 — Epic 28 (Section 37.7) | — |
| ЗАДАЧА | 1531–1532 | выявить события, кратко и саркастично описать; едкий комментарий 1–2 предложения на событие | — |
| ОГРАНИЧЕНИЕ | 1534–1535 | «Длина ответа строго не более {max_symbols} символов» | `{max_symbols}` ×1 |
| ФИНАЛ | 1537–1540 | приписка «самым главным шизом объявляется {username}» с новой строки + пояснение «(Вместо {username} подставь имя участника из атрибута author… без @. Никаких точек или других знаков после этой фразы)» (пояснение правлено Epic 28 — 37.7) | `{username}` ×2 |

### 36.3 Типографика и стиль v2 (отличия от старого промпта)

1. **Ленивая печать:** регистр в начале предложений — случайный (НЕ «всё с маленькой буквы», как было). Текст читаем, но небрежен.
2. **Пунктуация:** точки и запятые обязательны (текст не сливается), запятые иногда пропускаются.
3. **Типографика:** только короткие дефисы `-` и обычные двойные кавычки `""`; КАТЕГОРИЧЕСКИ запрещены тире `—` и ёлочки `«»`.
4. **Запрет форматов:** никакого маркдауна (`**`, `*`, `_`, `#`), списков/пунктов, эмодзи.
5. **Абзацы:** сплошной текст, темы разделяются пустыми строками.
6. **Финал:** приписка с новой строки, после неё — никаких знаков. Автодописывание `_ensure_shiz_postfix` (33.7) продолжает работать: маркер «самым главным шизом объявляется» в новом промпте есть.

### 36.4 Тест-план (R27-2; 939 baseline, 0 регрессий)

| Тест (`tests/test_summary_prompts.py`) | Изменение |
|---|---|
| `test_system_prompt_byte_for_byte` | БЕЗ изменений логики. Только хелпер `_backlog_system_prompt`: слайс `lines[1517:1523]` → **`lines[1517:1540]`** (0-индекс = строки 1518–1540 1-индекс) + комментарий |
| `test_max_symbols_is_the_only_placeholder` | ПЕРЕПИСАТЬ (D72): regex-набор `{"max_symbols", "username"}` вместо счётчика `count("{") == 2` |
| `test_format_max_symbols` | БЕЗ изменений — «{max_symbols} символов» есть в «ОГРАНИЧЕНИЕ», «3800 символов» матчится |
| `test_shiz_marker_present` | БЕЗ изменений — маркер в «ФИНАЛЕ» |
| `test_system_and_compress_prompts_untouched` | БЕЗ изменений — сравнивает SYSTEM_PROMPT с `EXPECTED_SYSTEM_PROMPT` (новый эталон подтянется из хелпера автоматически); COMPRESS/EXTRACT не трогаются |

### 36.5 План доков (R27-3, T-208)

- **ARCHITECTURE.md** — строки 3332, 3342, 3514, 3670, 3676, 3732, 4198, 4221, 4242, 4257 (точечные правки выполнены в этом шаге) + Section 36 + header/СОДЕРЖАНИЕ.
- **MEMORY.md** — строки 72, 204, 221, 714: убрать «дословно заморожены (R11), НЕ менять» → «SYSTEM_PROMPT обновлён Epic 27 (R11 v2, v2.25.0), эталон backlog 1518–1540; COMPRESS_PROMPT/EXTRACT_PROMPT — заморожены»; новая строка-обновление в ленте сверху.
- **README.md** — строка 217 («кап размера ответа — только через промпт») остаётся верной; проверить, нет ли описаний старого стиля «всё с маленькой буквы» (при наличии — обновить).

### 36.6 План деплоя (T-209/T-210)

1. **T-210-A:** коммит на русском `feat(summary): Epic 27 — новый системный промпт + SUMMARY_ALIASES на прод (v2.25.0)` (код + тесты + `.env.example` + доки), push origin/master. `.env` в коммит НЕ попадает (gitignored ✓) — T-210-B.
2. **T-209-A:** ssh nik@198.46.175.136, cd /var/www/admin_bot → `cp .env .env.bak.epic27`; если `grep -c '^SUMMARY_ALIASES=' .env` = 0 → append строки из `.env.example:136` в одинарных кавычках в конец `.env`; если > 0 → заменить существующую строку (не плодить дубли).
3. **T-209-B:** `git pull` (ожидается fast-forward), `sudo systemctl restart admin_bot`. Нюанс: бот не отвечает на SIGTERM ~95с (pre-existing, MEMORY.md) — первый стоп может кончиться SIGKILL старого процесса, вторая попытка — OK. НЕ паниковать при долгом стопе (backlog-риск 4).
4. **T-209-C:** верификация — `systemctl status admin_bot` → active (running) + НОВЫЙ Main PID (текущий 926618); `grep SUMMARY_ALIASES .env` → строка на месте, JSON валиден (`python -c "import json,sys; json.loads(<value>)"`); `journalctl -u admin_bot -n 200` (через `sudo -S`) → 0 traceback, «SmartModule Summary initialized»; отчёт пользователю (PID, v2.25.0).

### 36.7 Риски

| # | Риск | Митигация |
|---|------|-----------|
| 1 | 3 пары скобок → старый счётчик `count("{") == 2` падает | D72 — тест переписан на набор плейсхолдеров (36.4) |
| 2 | Хрупкий диапазон строк хелпера: будущая правка backlog выше блока сдвинет эталон | Диапазон фиксирован 1517:1540 (v3 — Epic 28, 23 строки); при сдвиге — обновить в T-217-B/C (backlog-риск 2) |
| 3 | Хвостовые пробелы/артефакты → рассинхрон байт-в-байт | D74 — эталон нормализован без хвостовых пробелов; `git diff --check` перед коммитом |
| 4 | SIGTERM ~95с на рестарте прода | pre-existing; дождаться / вторая попытка рестарта (36.6.3) |
| 5 | Поведенческое изменение: алиасы меняют имена в /summary (alias вместо username) | Ожидаемо пользователем (backlog-риск 5); `_ensure_shiz_postfix` возьмёт `author_name` с алиасом (A8) |
| 6 | JSON с кавычками/кириллицей в .env сломает парсинг | Значение в одинарных кавычках; валидация `json.loads` на сервере до рестарта (36.6.4) |

### 36.8 Сводка для Builder/DevOps (T-207 → T-210) и файлы

1. **T-207** — `services/summary_prompts.py`: `SYSTEM_PROMPT` = новый текст ДОСЛОВНО (backlog 1518–1540, 23 строки, без хвостовых пробелов — v3 Epic 28, 37.7), docstring модуля; `tests/test_summary_prompts.py`: хелпер 1517:1540 + тест набора плейсхолдеров (36.4); полный pytest — 939 passed.
2. **T-208** — доки: ARCHITECTURE.md (правки уже внесены — верифицировать), MEMORY.md (36.5), README.md.
3. **T-210** — коммит + пуш; **T-209** — прод: .env (бэкап + SUMMARY_ALIASES) + git pull + restart + верификация (36.6).

**Файлы:** изменить — `services/summary_prompts.py`, `tests/test_summary_prompts.py`, `README.md` (при необходимости), `plans/MEMORY.md`, `plans/board.md`, `plans/backlog.md` (статусы); закоммитить — `.env.example` (SUMMARY_ALIASES, не секрет — D75); `plans/ARCHITECTURE.md` — уже обновлён @Architect. **НЕ трогать:** `COMPRESS_PROMPT`, `EXTRACT_PROMPT`, `llm_client.py`, `summary_memory.py` (vec0), `summary_generator.py` (кроме проверки строки 113 — менять не нужно), GraphRAG-код, `.env` локальный.

---

## 37. Epic 28 — Качество памяти: векторы, репосты, алиасы, очистка (v2.26.0)

> **Дата:** 2026-08-16
> **Статус:** DESIGN ✅ (@Architect, шаг 2/3). T-211…T-219 → READY FOR BUILDER; T-220 → @Builder + @DevOps + @PM.
> **Цель:** закрыть 4 проблемы качества памяти SmartModule: (1) автолечение L3-векторов при dimension mismatch (старые 768-dim против фактических 3072-dim); (2) forward-маркировка репостов (БД → observer → XML → L2-цитаты → L3/GraphRAG); (3) ре-резолв алиасов на лету (XML/L2/шиз) + правила 6/7 в SYSTEM_PROMPT; (4) cleanup-модуль типографики сырого ответа LLM. Требования R28-1…R28-6, решения D76–D80 — `plans/backlog.md` Epic 28.
> **Источник истины промпта:** как и в 36.1 C1 — ТОЛЬКО блок R11 в `plans/backlog.md`; после T-217-B диапазон блока **1518–1540** (формула 37.7). ARCHITECTURE текст не дублирует.

### 37.1 Цели и границы

| # | Проблема | Решение | Скоуп |
|---|----------|---------|-------|
| 1 | Векторы L3 | Автолечение размерности vec0 (37.5), пустой KNN → FTS5 | `summary_memory.py` |
| 2 | Репосты | `is_forward`/`forward_source` (37.2, 37.3) | `database.py`, `handlers/summary.py`, `summary_xml.py`, `summary_generator.py`, `summary_memory.py` |
| 3 | Алиасы | Ре-резолв на лету (37.4) + правила 6/7 промпта (37.7) | `summary_xml.py`, `summary_generator.py`, `summary_prompts.py` |
| 4 | Типографика ответа | `summary_cleanup.py` (37.6) | новый модуль + `summary_generator.py` |

**Границы (НЕ трогать):** `COMPRESS_PROMPT`/`EXTRACT_PROMPT` (байт-в-байт тесты), `llm_client.py`, подстановка `SYSTEM_PROMPT.replace("{max_symbols}", …)` (`summary_generator.py:113`), порядок существующих атрибутов тега `<message>`, маркер `_ensure_shiz_postfix`, роутер-порядок `bot.py`, таблицу `smart_archive_facts` (текст фактов НЕ жертвуется — D78), `_SCHEMA_SQL` кроме блока `smart_messages`.

### 37.2 Миграция БД smart_messages (T-211, R28-1)

**Свежие БД** — заменить блок `smart_messages` в `_SCHEMA_SQL` (services/database.py:50–59) целиком (новые колонки в КОНЦЕ — порядок идентичен результату ALTER на старых БД):

```sql
        CREATE TABLE IF NOT EXISTS smart_messages (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER,
            chat_id         INTEGER NOT NULL,
            text            TEXT,
            reply_to_id     INTEGER,
            timestamp       INTEGER NOT NULL,
            media_type      TEXT NOT NULL DEFAULT 'text',
            author_name     TEXT NOT NULL DEFAULT '',
            is_forward      INTEGER NOT NULL DEFAULT 0,
            forward_source  TEXT NOT NULL DEFAULT ''
        );
```

**Существующие прод-БД** — в `DatabaseService.initialize()` сразу ПОСЛЕ блока миграции `dead_page_posts` (database.py:120–125), ДО блока `PRAGMA foreign_keys` (перед строкой 127), прецедент — тот же паттерн try/except OperationalError:

```python
        # Epic 28 (R28-1): forward-marking columns for existing smart_messages tables
        try:
            await self.db.execute(
                "ALTER TABLE smart_messages ADD COLUMN is_forward INTEGER NOT NULL DEFAULT 0"
            )
            await self.db.commit()
        except aiosqlite.OperationalError:
            pass  # Column already exists
        try:
            await self.db.execute(
                "ALTER TABLE smart_messages ADD COLUMN forward_source TEXT NOT NULL DEFAULT ''"
            )
            await self.db.commit()
        except aiosqlite.OperationalError:
            pass  # Column already exists
```

**`save_smart_message`** (database.py:358) — kw-параметры в КОНЕЦ сигнатуры с дефолтами; все существующие вызовы совместимы: позиционные 7-арг вызовы в `tests/test_database.py` (~207–329), `tests/test_summary_memory.py:56`, `tests/test_graphrag_memory.py:73` и kw-вызов observer `handlers/summary.py:109`:

```python
    async def save_smart_message(
        self,
        user_id: int,
        chat_id: int,
        text: str | None,
        reply_to_id: int | None,
        timestamp: int,
        media_type: str,
        author_name: str,
        is_forward: bool = False,
        forward_source: str = "",
    ) -> int:
        cursor = await self.db.execute(
            "INSERT INTO smart_messages "
            "(user_id, chat_id, text, reply_to_id, timestamp, media_type, author_name, "
            "is_forward, forward_source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, chat_id, text, reply_to_id, timestamp, media_type, author_name,
             int(is_forward), forward_source),
        )
```

**SELECT'ы** — добавить `is_forward, forward_source` в список колонок (ровно три правки):
- `get_smart_window` (database.py:387): `"SELECT id, user_id, chat_id, text, reply_to_id, timestamp, media_type, author_name, is_forward, forward_source "`
- `get_smart_raw` (database.py:399): тот же список.
- `search_messages_fts` (database.py:470–471): `"m.media_type, m.author_name, m.is_forward, m.forward_source "`

### 37.3 Forward-маркировка: observer → XML → L2 → L3 (T-212/T-213/T-214/T-215, R28-1)

**Observer (`handlers/summary.py`):** после расчёта `reply_to_id` (строка ~102), до `save_smart_message`:

```python
        origin = getattr(message, "forward_origin", None)   # getattr-защита (риск 7)
        is_forward = origin is not None
        forward_source = _extract_forward_source(origin) if is_forward else None
        ...
            await _db.save_smart_message(
                ...,
                is_forward=is_forward,
                forward_source=(forward_source or "")[:_FORWARD_SOURCE_MAX_CHARS],
            )
```

**Решение по алиасам в observer:** observer УЖЕ имеет доступ к алиасам — модульный глобал `_aliases` заполняется `setup_summary(generator, db, aliases, bot_id)` (`bot.py:129`) и уже используется для author в строке 103 `handlers/summary.py`. Никаких новых сигнатур в `setup_summary` не требуется. Для `MessageOriginUser` имя источника резолвим через тот же `_aliases.resolve(...)` — имена источника консистентны с author-каскадом (alias → nickname → username). `forward_source` хранит ТОЛЬКО строку источника; ре-резолв алиасов в XML (37.4) применяется к `author_name` переславшего — двойного резолва нет, и для источника имя через алиасы НЕ обязательно (строка-источник), но так имена в XML согласованы.

**Точная функция** (модульный уровень, рядом с `_detect_media_type`, строки 48–66):

```python
_FORWARD_SOURCE_MAX_CHARS = 100


def _extract_forward_source(origin) -> str | None:
    """Epic 28 (R28-1): label of the forward origin; None = save as ordinary."""
    if origin is None:
        return None
    try:
        if isinstance(origin, types.MessageOriginChannel):
            chat = getattr(origin, "chat", None)
            title = (getattr(chat, "title", None) or "").strip()
            username = (getattr(chat, "username", None) or "").strip()
            signature = (getattr(origin, "author_signature", None) or "").strip()
            parts = [title] + ([f"@{username}"] if username else []) + ([signature] if signature else [])
            return " ".join(parts) or None
        if isinstance(origin, types.MessageOriginUser):
            sender = getattr(origin, "sender_user", None)
            if sender is None:
                return None
            if _aliases is not None:
                return _aliases.resolve(
                    sender.id,
                    nickname=_build_nickname(sender),
                    username=getattr(sender, "username", None),
                )
            nickname = _build_nickname(sender)
            return nickname or (getattr(sender, "username", None) or str(sender.id)).lstrip("@")
        if isinstance(origin, types.MessageOriginHiddenUser):
            name = getattr(origin, "sender_user_name", None)
            return (name or "").strip() or None
        if isinstance(origin, types.MessageOriginChat):
            chat = getattr(origin, "sender_chat", None)
            title = (getattr(chat, "title", None) or "").strip()
            username = (getattr(chat, "username", None) or "").strip()
            parts = [title] + ([f"@{username}"] if username else [])
            return " ".join(parts) or None
        return None
    except Exception:
        logger.warning("SmartModule observer: forward source extraction failed", exc_info=True)
        return None
```

Семантика: `is_forward=True` при любом `forward_origin` (даже если метку извлечь не удалось — содержание всё равно не принадлежит переславшему); `forward_source=""` допустимо. Обрезка 100 симв. при сохранении (см. выше); весь блок детекции в существующем try/except observer — сбой не роняет сохранение (T-212-C).

**XML (`summary_xml.py` `_build_element`)** — атрибуты В КОНЕЦ тега, порядок существующих не меняется (ассерты `test_summary_xml.py` — substring-матчи, остаются зелёными). Итоговый порядок: `id, timestamp, author, reply_to_id, type, [is_forward, forward_source]`:

```python
        extra = ""
        if row.get("is_forward"):
            extra += ' is_forward="true"'
            source = (row.get("forward_source") or "").strip()
            if source:
                extra += f' forward_source="{_escape(source, quote=True)}"'
        return (
            f'<message id="{msg_id}" timestamp="{iso}" author="{_escape(author, quote=True)}" '
            f'reply_to_id="{reply_attr}" type="{media_type}"{extra}>{_escape(body)}</message>'
        )
```

**L2-цитаты (`summary_generator.py:91–95`)** — формат маркера: `Оля (репост из "Канал X"): текст` (без квадратных скобок — как текущий формат цитат; двойные кавычки по типографике проекта). Новые хелперы:

```python
    def _resolve_author(self, row) -> str:
        if self.aliases is not None:
            return self.aliases.resolve(
                int(row["user_id"] or 0), (row["author_name"] or None), None
            )
        return row["author_name"] or "кто-то"

    def _format_l2_quote(self, row) -> str:
        name = self._resolve_author(row)
        if row.get("is_forward"):
            source = (row.get("forward_source") or "").replace('"', "'").strip()
            name = f'{name} (репост из "{source}")' if source else f"{name} (репост)"
        return f'{name}: {row["text"]}'
```

**`_build_batch_text` (`summary_memory.py:125–134`)** — формат строк: `[Оля (репост из "Канал X")]: текст` (нейтральный: квадратные скобки — существующий паттерн, двойные кавычки — разрешённая типографика правила 3; «» не используются; cleanup применяется только к ответу LLM — конфликтов нет). Вложенные `"` в forward_source заменяются на `'` (защита парсинга):

```python
        if row.get("is_forward"):
            source = (row.get("forward_source") or "").replace('"', "'").strip()
            author = f'{author} (репост из "{source}")' if source else f"{author} (репост)"
        lines.append(f"[{author}]: {text}")
```

`COMPRESS_PROMPT` не трогаем (T-215-B); строки без `is_forward` — старое поведение байт-в-байт.

### 37.4 Ре-резолв алиасов на лету (T-213-D, T-214-A/B, D76)

Паттерн (зафиксирован в backlog T-213-D): `aliases.resolve(int(row["user_id"] or 0), author_name or None, None)` — сохранённый `author_name` передаётся как `nickname`: алиас (если задан) побеждает устаревшее имя; иначе fallback на сохранённое имя (каскад AliasResolver не ломается). Применяется:

1. **`summary_xml.py` `_build_element`** — ВСЕГДА при `aliases is not None` (не только при пустом имени):
```python
        author = (row["author_name"] or "").strip()
        if aliases is not None:
            # Epic 28 (T-213-D): алиас побеждает устаревший author_name старых строк
            author = aliases.resolve(int(row["user_id"] or 0), author or None, None)
```
   Существующие тесты зелёные: `test_empty_author_uses_alias_resolver` (author_name="", user_id=10, alias "главный") → "главный"; `test_empty_author_no_resolver` (без aliases) → `author=""`; `test_single_message` (без aliases) → "вася".
2. **`summary_generator.py` L2-цитаты** — через `_resolve_author(row)` (37.3).
3. **`_most_active_author(rows, aliases=None)`** — остаётся staticmethod с новым опциональным параметром; в `_ensure_shiz_postfix` берём `aliases = getattr(self, "aliases", None)` (тесты зовут `SummaryGenerator._ensure_shiz_postfix(None, ...)` — при self=None getattr вернёт None → старое поведение):
```python
        name = SummaryGenerator._most_active_author(rows, getattr(self, "aliases", None))
```
   Внутри `_most_active_author`: `name = aliases.resolve(int(row["user_id"] or 0), stored or None, None) if aliases is not None else stored` (stored = `(row["author_name"] or "").strip().lstrip("@")`).

**Сигнатура `build()`:** параметр уже существует (`build(self, messages, aliases=None)`) и так называется в вызовах `summary_generator.py:86` и тестах (`aliases=resolver`). НЕ переименовывать в `resolver` — только уточнить аннотацию: `aliases: AliasResolver | None = None` (совместимость).

### 37.5 Векторное автолечение L3 (T-216, R28-2, D78/D79)

**Итоговый алгоритм (основной источник размерности — probe embed; DDL — только проверка существующей таблицы):**
- Пробный `embed(["probe"])` — ПЕРВИЧНЫЙ источник actual_dim; делается ТОЛЬКО если sqlite-vec успешно загрузился. Ровно **1 вызов эмбеддингов на старт** (0 вызовов, если расширение не загрузилось). Весь вызов в try/except → сбой = WARNING + FTS5-фоллбек, старт не ломается (D79).
- DDL-разбор (`SELECT sql FROM sqlite_master WHERE type='table' AND name='smart_archive'` → regex `float\[(\d+)\]`) — только чтобы узнать stored_dim существующей таблицы.
- **DROP только при фактическом расхождении** `stored_dim != actual_dim` (не по конфигу) → пересоздание `float[{actual_dim}]`; `smart_archive_facts` НЕ трогается (D78).
- WARNING при `actual_dim != settings.EMBEDDING_DIM` (конфиг vs реальный API).
- **INSERT-pадение с Dimension mismatch в рантайме** (`_save_archive_embedding`) — живой DROP НЕ делаем: `self._vec_available = False` (FTS5 до рестарта) + ERROR-лог; автолечение добьёт на следующем старте (безопаснее, чем DROP при работающем KNN).
- `self._vec_dim = actual_dim` — атрибут `MemoryManager` (для логов/диагностики); `__init__` дополняется `self._vec_dim = None`.

Точный код `initialize()` (замена существующего, summary_memory.py:162–185; `re` уже импортирован строкой 9):

```python
    async def initialize(self) -> bool:
        """Load sqlite-vec + self-heal dimension mismatch (Epic 28, R28-2). Never raises."""
        self._vec_available = False
        self._vec_dim = None
        try:
            import sqlite_vec

            await self.db.db.enable_load_extension(True)
            await self.db.db.load_extension(sqlite_vec.loadable_path())
            actual_dim = None
            try:
                vectors = await self.llm.embed(["probe"])
                if vectors and vectors[0]:
                    actual_dim = len(vectors[0])
            except Exception:
                logger.warning("SmartModule: probe embed failed — FTS5 fallback", exc_info=True)
            if actual_dim is None:
                return False
            if actual_dim != int(settings.EMBEDDING_DIM):
                logger.warning(
                    "SmartModule: EMBEDDING_DIM=%s != actual API dim=%d — using actual",
                    settings.EMBEDDING_DIM, actual_dim,
                )
            stored_dim = None
            cursor = await self.db.db.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='smart_archive'"
            )
            row = await cursor.fetchone()
            if row and row["sql"]:
                match = re.search(r"float\[(\d+)\]", row["sql"])
                if match:
                    stored_dim = int(match.group(1))
            if stored_dim is not None and stored_dim != actual_dim:
                logger.warning(
                    "SmartModule: vec dimension mismatch (stored=%d, actual=%d) — "
                    "dropping smart_archive (facts in smart_archive_facts are kept)",
                    stored_dim, actual_dim,
                )
                await self.db.db.execute("DROP TABLE smart_archive")
            await self.db.db.execute(_VEC_TABLE_SQL.format(dim=actual_dim))
            await self.db.db.commit()
            self._vec_dim = actual_dim
            self._vec_available = True
            logger.info("SmartModule: sqlite-vec loaded (dim=%d)", actual_dim)
        except Exception:
            logger.warning(
                "SmartModule: sqlite-vec unavailable — FTS5 fallback (R3)",
                exc_info=True,
            )
        finally:
            try:
                await self.db.db.enable_load_extension(False)
            except Exception:
                pass
        return self._vec_available
```

**Пустой KNN → FTS5** (точное место — `vector_search`, summary_memory.py:221–241): вернуть результат только если непуст; при пустом — INFO-лог и проваливание в `_fts_search_archive`:

```python
                if vectors and vectors[0]:
                    facts = await self._search_archive_knn(chat_id, vectors[0], limit)
                    if facts:
                        logger.info(
                            "SmartModule L3: knn_hits=%d | chat_id=%s", len(facts), chat_id
                        )
                        return facts
                    logger.info(
                        "SmartModule L3: KNN empty — FTS5 fallback | chat_id=%s", chat_id
                    )
```

**Рантайм-гард `_save_archive_embedding`** (summary_memory.py:407–421) — перед общим except вставить проверку сообщения ошибки:

```python
        except Exception as exc:
            message = str(exc).lower()
            if "dimension" in message or "mismatch" in message:
                self._vec_available = False
                logger.error(
                    "SmartModule L3: dimension mismatch on INSERT — vec disabled until "
                    "restart (self-heal on next start) | fact_id=%d",
                    fact_id, exc_info=True,
                )
            else:
                logger.warning(
                    "SmartModule L3: embed/vec insert failed for fact_id=%d — fact stays in FTS5 only",
                    fact_id, exc_info=True,
                )
```

### 37.6 Cleanup-модуль типографики (T-218, R28-3)

**Новый файл `services/summary_cleanup.py`** (полный текст):

```python
"""Epic 28 — cleanup of raw LLM summary text before postprocessing (R28-3).

The model occasionally breaks SYSTEM_PROMPT rule 3: long dashes and «ёлочки»
slip into the answer. This module normalizes the raw generate() output BEFORE
_ensure_shiz_postfix. Adding a rule = adding one (old, new) pair to REPLACEMENTS.
"""

REPLACEMENTS = (
    ("«", '"'),
    ("»", '"'),
    ("„", '"'),
    ("“", '"'),
    ("—", "-"),
    ("–", "-"),
)


def cleanup_llm_text(text: str) -> str:
    """Replace forbidden typography in the raw LLM answer. Never raises."""
    for old, new in REPLACEMENTS:
        text = text.replace(old, new)
    return text
```

**Вставка в `summary_generator._run`** — сразу ПОСЛЕ `llm.generate` и лога сырого ответа, ДО `_ensure_shiz_postfix` (лог остаётся честным raw; шиз-маркер запрещённых символов не содержит — порядок безопасен):

```python
            raw = await self.llm.generate(...)
            logger.info("summary LLM raw response ...")   # ← лог ДО очистки
            raw = cleanup_llm_text(raw)                   # Epic 28 (R28-3)
            text = self._ensure_shiz_postfix(raw, rows)
```

Импорт: `from services.summary_cleanup import cleanup_llm_text` в `summary_generator.py`.

### 37.7 SYSTEM_PROMPT v3: правила 6 и 7 (T-217, R28-4, D76/D77)

**Правило 6 (дословно, вставляется после пункта 5 блока «ПРАВИЛА ОФОРМЛЕНИЯ И СТИЛЬ»):**

> 6. Имена участников: в атрибуте author каждого сообщения стоит готовое имя участника. Если участнику задан алиас, он указан именно в этом атрибуте, поэтому используй его дословно и не имеешь права переименовывать участника. Если алиаса нет, можешь называть участника свободно: ник или юзернейм, при этом разрешена креативная интерпретация ника (например, участника с эмодзи-пейзажем в нике можно назвать "человек с пейзажем в нике"). В финальной приписке используй имя из атрибута author того участника, которого объявил шизом.

**Правило 7 (дословно, сразу после правила 6):**

> 7. Репосты: сообщение с атрибутом is_forward="true" переслано участником из атрибута author, но его содержание принадлежит источнику из атрибута forward_source. Не приписывай содержание репоста переславшему участнику.

**Проверки конфликтов (D77):** правила используют только `""` и `-` (согласовано с правилом 3), не содержат маркдауна/эмодзи/списков (правило 4), не трогают структуру абзацев (правило 5), не меняют «ЗАДАЧА/ОГРАНИЧЕНИЕ/ФИНАЛ». Атрибуты упомянуты БЕЗ фигурных скобок (`author`, `is_forward="true"`, `forward_source`) → набор плейсхолдеров остаётся `{"max_symbols", "username"}`: `{max_symbols}` ×1, `{username}` ×2 (3 пары скобок — тест D72 зелёный без изменений).

**Решение про пояснение финала:** минимальная правка — «реальный ник из контекста» → «имя участника из атрибута author» (согласовано с правилом 6: финал берёт имя из author). D73 сохраняется (пояснение — часть дословного промпта), остальной текст пояснения не меняется. Новая строка: `(Вместо {username} подставь имя участника из атрибута author без символа @. Никаких точек или других знаков после этой фразы).` Эталон в backlog обновляется в любом случае (T-217-B) — байт-в-байт тест не пострадает.

**Формула диапазона (для Builder, T-217-B/C/D):** в блок R11 вставляются ровно **2 строки** (правила 6 и 7, после строки 5, перед пустой строкой и «ЗАДАЧА:»); итог — **23 строки**, диапазон **1518–1540**, слайс `lines[1517:1540]`. Общая формула: `новый_конец = 1538 + N_вставленных_строк`. ⚠️ Если Builder вставит иначе (лишние/недостающие пустые строки) — пересчитать диапазон и обновить его ВЕЗДЕ (grep «1518–15»): `tests/test_summary_prompts.py` (хелпер), ARCHITECTURE.md (36.2/36.4/36.5/36.7/36.8), MEMORY.md, board.md, а также эталонную заметку под блоком R11 в backlog (сейчас ~1543–1545). Плесхолдер-тест и docstring `summary_prompts.py` (Epic 28, новый диапазон) — тоже T-217-A.

### 37.8 Тест-план (T-219, R28-5; 939 baseline + новые, 0 регрессий)

| Задача | Тесты |
|--------|-------|
| T-211 (БД) | свежая БД: колонки с дефолтами (0/'') в CREATE-пути; мигрированная: вручную созданная старая таблица → `initialize()` → ALTER добавил колонки; `save_smart_message` с kw и без (дефолты); 3 SELECT'а возвращают новые поля |
| T-212 (observer) | 4 типа origin → строки источника (Channel с title/username/author_signature; User через алиас и без; HiddenUser; Chat); неизвестный тип/None → не падает, `is_forward=True` при origin, `forward_source=""`; обрезка 100 симв.; исключение в экстракции → сообщение сохранено обычным |
| T-213 (XML) | атрибуты в конце тега (порядок `id,timestamp,author,reply_to_id,type[,is_forward][,forward_source]`); существующие substring-ассерты зелёные; escape forward_source (`&`, `"`); ре-резолв: alias побеждает stale author_name; без алиаса — сохранённое имя; без aliases — старое поведение |
| T-214 (генератор) | L2-цитата с алиасом; маркер `(репост из "X")`; `_most_active_author(rows, aliases)`; `_ensure_shiz_postfix(None, ...)` без алиасов — старое поведение (существующие 6 тестов TestShizPostfix зелёные) |
| T-215 (batch) | `[Оля (репост из "Канал X")]: текст`; без source → `[Оля (репост)]: текст`; не-репост — байт-в-байт старый; skip_empty работает |
| T-216 (автолечение) | vec import fail → 0 probe-вызовов, FTS5; probe fail (LLM-ошибка) → старт ок, FTS5; actual(3) != settings.EMBEDDING_DIM → WARNING; таблицы нет → создана с actual_dim; stored 768 vs actual 3072 → DROP + пересоздание, факты smart_archive_facts целы; пустой KNN → вызван FTS5-путь; INSERT-mismatch → `_vec_available=False` |
| T-217 (промпт) | байт-в-байт == блок backlog (новый диапазон); набор плейсхолдеров `{max_symbols, username}`; `test_format_max_symbols`/`test_shiz_marker_present` зелёные |
| T-218 (cleanup) | 6 пар замен по отдельности + смешанный текст; идемпотентность; чистый текст не меняется; cleanup применён ДО `_ensure_shiz_postfix` (шпион порядка) |

### 37.9 Деплой + инструкция пользователю (T-220, R28-6, D80)

**Рекомендация DevOps:** правка прод `.env` **НЕ требуется** — автолечение (37.5) чинит размерность само при рестарте (probe embed → DROP/пересоздание vec0; факты сохраняются). `EMBEDDING_DIM=3072` в прод `.env` — **опционально** (только чтобы убрать WARNING «EMBEDDING_DIM=768 != actual API dim=3072»; с бэкапом `.env.bak.epic28`). Остальное: git pull → `sudo systemctl restart admin_bot` (SIGTERM ~95с — pre-existing, не паниковать) → верификация: в логах НЕТ `Dimension mismatch`, есть `sqlite-vec loaded (dim=3072)` (или WARNING probe — тогда FTS5), 0 traceback.

**Текст инструкции для пользователя (короткий):**
> Действия не нужны — после обновления бот сам починит векторную память при старте (старые векторы будут пересозданы, текстовые факты сохранятся). Если хочешь чистые логи: в прод `.env` можно добавить `EMBEDDING_DIM=3072` (с бэкапом), но это необязательно.

### 37.10 Риски

| # | Риск | Митигация |
|---|------|-----------|
| 1 | DROP smart_archive — жертва векторной истории (~день) | D78; только при фактическом расхождении stored≠actual; факты-текст не трогаются; WARNING с причинами |
| 2 | Probe embed на старте — задержка/стоимость | 1 вызов «probe» (1 токен), только при загруженном vec; try/except → FTS5, старт не ломается (D79) |
| 3 | Живой DROP при работающем KNN | НЕ делаем: mismatch в рантайме → `_vec_available=False` до рестарта |
| 4 | Сдвиг эталона R11 (1518–1538 → 1518–1540) | Формула 37.7; T-217-B/C/D + grep-проверка всех ссылок; иначе байт-в-байт тест падает |
| 5 | Позиционная совместимость save_smart_message | kw в конце с дефолтами; перечисленные вызовы (37.2) не меняются |
| 6 | forward_origin отсутствует в старых aiogram/типах | getattr-защита + try/except в экстракции; сообщение сохраняется обычным |
| 7 | Cleanup vs шиз-маркер | Маркер не содержит запрещённых символов; cleanup до `_ensure_shiz_postfix` безопасен |
| 8 | `_ensure_shiz_postfix(None, …)` в тестах | `getattr(self, "aliases", None)` — self=None → None → старое поведение |
| 9 | Ре-резолв меняет author XML по сравнению со старыми строками | Осознанно (D76): алиас приоритетнее устаревшего author_name; без алиаса поведение идентично |

**Файлы:** `services/database.py`, `handlers/summary.py`, `services/summary_xml.py`, `services/summary_generator.py`, `services/summary_memory.py`, `services/summary_cleanup.py` (НОВЫЙ), `services/summary_prompts.py`, `tests/test_database.py`, `tests/test_summary_handlers.py`, `tests/test_summary_xml.py`, `tests/test_summary_generator.py`, `tests/test_summary_memory.py`, `tests/test_summary_prompts.py`, `plans/backlog.md` (эталон R11 + статусы), `plans/MEMORY.md`, `plans/board.md`, `README.md`. **НЕ трогать:** `COMPRESS_PROMPT`/`EXTRACT_PROMPT`, `llm_client.py`, `bot.py` (кроме ничего — wiring не меняется), `config/settings.py` (EMBEDDING_DIM не меняем — автолечение), `.env.example` (опционально: комментарий про EMBEDDING_DIM).
