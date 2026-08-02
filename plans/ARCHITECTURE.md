# ARCHITECTURE.md — AdminBot

> **Версия:** v2.18.0
> **Дата:** 2026-08-02
> **Статус:** Архитектурный контракт. Содержит дизайн Epic 18-20. Реализация НЕ начата.
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

@Orchestrator Epic 20 architecture ready, passing the baton.
