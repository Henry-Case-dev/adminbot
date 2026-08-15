# ARCHITECTURE.md — AdminBot

> **Версия:** v2.21.0 (текущий дизайн: Epic 23)
> **Дата:** 2026-08-16
> **Статус:** Архитектурный контракт. Секции 1–29: дизайн Epic 18–21 (реализованы и задеплоены). Секция 30: дизайн Epic 22 (v2.20.0) — IMPLEMENTED ✅. Секция 31: конвенция media/. Секция 32: дизайн Epic 23 (v2.21.0) — DONE & DEPLOYED ✅ (672 теста; коммит `756d237`, прод v2.21.0, PID 917681).
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
