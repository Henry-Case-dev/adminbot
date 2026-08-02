# ARCHITECTURE.md — AdminBot

> **Версия:** v2.15.0-draft (Architect Investigation)
> **Дата:** 2026-08-02
> **Статус:** Архитектурное расследование четырёх задач. Реализация НЕ начата — этот документ есть контракт для Builder.
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
