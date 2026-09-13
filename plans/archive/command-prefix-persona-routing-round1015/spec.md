# Спека F6 — `command-prefix-persona-routing-round1015` (Обязательный префикс команд, имя персоны, приоритеты)

> **Статус:** ✅ COMPLETED (Step 4 @Builder, 14.09.2026). T-1594…T-1600 выполнены; гейты T-1601/T-1602 — за @Reviewer/@PM. pytest 5694 passed / 0 failed.
> **Раунд:** 10.15. **Тип:** backend (routing). **Приоритет:** P0 — **главный регресс-риск раунда**. **T-ID:** T-1593…T-1602.
> **ТЗ:** `plans/current_task.md` §6 + UPD §1-2 (строки 79-125). **ADR:** [`adr-1015-1-command-prefix-policy.md`](adr-1015-1-command-prefix-policy.md).
> **Конфликт файлов:** `handlers/search.py`, `handlers/youtube.py`, `handlers/web.py`, `handlers/checkup.py`, `handlers/video_download.py`, `handlers/direct_chat.py`, `services/smartmodule_phrases.py`; **`bot.py` — только при необходимости DI-kwargs, порядок роутеров НЕ трогать**.
> **Baseline:** HEAD `798e044`; pytest 5589/0; каталог 435/406/411/90/88/19.

## 1. Цель

Функциональные команды срабатывают только по явному обращению: **Префикс + Триггер**, где Префикс = `active_persona.name` («Олег », «Олег, ») либо «Бот »/«Бот, », если имя не задано. **Само наличие непустого Имени — триггер системы** (никакого рубильника `flags.command_prefix_enabled`). При заданном имени дефолтные ботворд-триггеры (`бот`/`ботик`/`ботяра`) отключаются. Функциональная команда имеет наивысший приоритет и **не уходит в LLM** за обычным ответом.

## 2. Ключевое решение по совместимости (UPD §1, см. ADR-1015-1)

**Отдельного флага НЕТ.** Триггер = **непустое `active_persona.name`**:

- **Имя заполнено** (напр. «Олег»): префикс команд = `Олег, ` (варианты разделителя — пробел/`,`/`:`/`!`/дефис); дефолтные триггеры `бот`/`ботик`/`ботяра` **отключаются** (и для команд, и для обычного ответа direct_chat).
- **Имя пусто** (текущий сид 10.14 — пустая глобальная персона): префикс = `Бот, ` (семейство `бот`/`ботик`/`ботяра`); дефолтные триггеры **остаются активными**.

**Мягкий переход без флага:** пустой глобальный дефолт ⇒ чаты не теряют обычные ботворд-ответы. Меняется только функциональный путь: bare-триггеры (`загугли …` без «Бот,») перестают срабатывать — это и есть цель фичи. Существующие чаты с непустым именем получают новую семантику сразу (отключение дефолтов) — обратимость только через очистку поля Имя (не через kill-switch). **Rollback = `git revert` + очистка Имени.**

Обоснование отказа от флага: фича должна работать «из коробки»; флаг добавлял ручное включение и +1 каталог-ключ, что владелец отклонил (UPD §1).

## 3. Точный реестр команд (UPD §2 — захардкодить именно эти)

Канонический список — новый модуль **`services/command_registry.py`** (код, без каталога). Подстановка Имени вместо «Бот» выполняется резолвом префикса (§4), а не дублированием строк.

| # | Префиксный триггер (канон) | Хендлер | Роутер (bot.py) |
|---|---|---|---|
| 1 | `найди` | `handlers/search.py` | 0d |
| 2 | `поищи` | `handlers/search.py` | 0d |
| 3 | `загугли` | `handlers/search.py` | 0d |
| 4 | `транскрипт` | `handlers/youtube.py` | 0e |
| 5 | `че за видос` | `handlers/youtube.py` | 0e |
| 6 | `о чем видео` | `handlers/youtube.py` | 0e |
| 7 | `поясни за видос` | `handlers/youtube.py` | 0e |
| 8 | `поясни за ссылку` | `handlers/web.py` | 0f |
| 9 | `че по ссылке` | `handlers/web.py` | 0f |
| 10 | `о чем статья` | `handlers/web.py` | 0f |
| 11 | `выжимка` | `handlers/web.py` | 0f |
| 12 | `ты в порядке` | `handlers/checkup.py` | 0g |
| 13 | `живой?` (**строго так; слово «собака» убрать**) | `handlers/checkup.py` | 0g |
| 14 | `чекни здоровье` | `handlers/checkup.py` | 0g |
| 15 | `скачай` | `handlers/video_download.py` | 4e |
| 16 | `загрузи` | `handlers/video_download.py` | 4e |
| 17 | `стяни` | `handlers/video_download.py` | 4e |

**ИСКЛЮЧЕНИЯ (вызываются ОДНИМ СЛОВОМ, без префикса):**
- `чекап` → `handlers/checkup.py` (bare, как сейчас);
- `фактчек` → `handlers/factcheck.py` (bare, как сейчас).

```python
# services/command_registry.py (новый; имена — канон UPD §2, регистронезависимо)
FUNCTIONAL_COMMANDS: dict[str, tuple[str, ...]] = {
    "search":   ("найди", "поищи", "загугли"),
    "youtube":  ("транскрипт", "че за видос", "о чем видео", "поясни за видос"),
    "web":      ("поясни за ссылку", "че по ссылке", "о чем статья", "выжимка"),
    "checkup":  ("ты в порядке", "живой?", "чекни здоровье"),
    "download": ("скачай", "загрузи", "стяни"),
}
BARE_COMMANDS: tuple[str, ...] = ("чекап", "фактчек")
ALL_TRIGGERS: tuple[str, ...] = tuple(t for cmds in FUNCTIONAL_COMMANDS.values() for t in cmds)
_TRIGGER_RE = re.compile("|".join(re.escape(t) for t in
                                  sorted(ALL_TRIGGERS, key=len, reverse=True)), re.IGNORECASE)

def matches(text: str) -> bool:
    """Остаток начинается с любого канонического триггера (prefixed-путь)."""
    return bool(_TRIGGER_RE.match(str(text or "").strip()))

def matches_group(group: str, text: str) -> bool:
    """Остаток начинается с триггера конкретной группы (search/youtube/web/...)."""
    lowered = str(text or "").strip().lower()
    return any(lowered.startswith(t) for t in FUNCTIONAL_COMMANDS.get(group, ()))
```

**F6-U1 (снятые алиасы, осознанно):** legacy-алиасы, не входящие в канон, из префиксного пути **удаляются**: `перескажи видос`, `че в видосе` (youtube), `поясни за статью`, `че на сайте`, `перескажи статью` (web), `живой собака`, `пульс бота`, `как сервак`, `спизди`, `скачать` (checkup/download). Причина: UPD §2 «захардкодьте именно эти». Риск — в §11; при возражении владельца вернуть как «тихие» префиксные алиасы без публикации в гайде (не блокирует SPEC_READY).

## 4. Резолв префикса (точный алгоритм)

Новый модуль **`services/command_prefix.py`** (код, без каталога):
```python
from services import hot_config as hot
from services import bot_persona
from config.settings import settings

_DEFAULT_TOKENS = ("бот", "ботик", "ботяра")   # семейство ботвордов
# F6-Q2: эвристика склонений (только при len(name) >= 3)
_NAME_SUFFIXES = ("", "а", "я", "у", "ю", "ом", "ем", "е", "ы", "и")
_SEP = r"[\s,:.!\-]+"          # «Олег загугли», «Олег, загугли», «Олег: загугли»

def active_name() -> str:
    """Непустое имя персоны (sync-кэш) или '' (гейт flags.persona_enabled)."""
    if not hot.get("flags.persona_enabled", settings.PERSONA_ENABLED):
        return ""
    return str(bot_persona.get_cached_global_name() or "").strip()

def command_prefix_tokens() -> tuple[str, ...]:
    """Имя+склонения при непустом имени, иначе ботворд-семейство. Всё lower."""
    name = active_name().lower()
    if not name:
        return _DEFAULT_TOKENS
    if len(name) < 3:
        return (name,)
    return tuple(sorted({name + s for s in _NAME_SUFFIXES}))

def split_prefix(text: str) -> tuple[str | None, str]:
    """(совпавший токен, остаток) | (None, исходный текст). Только НАЧАЛО строки."""
    raw = str(text or "").lstrip()
    for tok in command_prefix_tokens():
        m = re.match(rf"(?i)^{re.escape(tok)}(?![0-9a-zа-яё_])(?:{_SEP})", raw)
        if m:
            return tok, raw[m.end():].lstrip()
    return None, text

def is_functional_command(text: str) -> bool:
    """Префикс + канонический триггер (для direct_chat-yield, §6)."""
    tok, rest = split_prefix(text)
    return tok is not None and command_registry.matches(rest)
```

- **F6-Q1 RESOLVED:** per-chat имя на sync-пути недоступно (10.14 L-ограничение) → `bot_persona.get_cached_global_name()` (sync, прогрев `load_global_cache()`); блокирующих PG-запросов нет.
- **F6-Q2 RESOLVED:** эвристический список окончаний, только для имён ≥3 симв.; точное совпадение всегда входит (`suffix=""`).
- **F6-Q3 RESOLVED (итерация 2):** дефолтные ботворды отключаются **iff `persona_enabled AND name non-empty`** — флаг `command_prefix_enabled` больше не участвует.
- **F6-Q4 RESOLVED:** reply/mention/@username — без обязательного префикса (приоритетнее, не меняются).

## 5. Интеграция в функциональные хендлеры

**search.py (`:93-101`, `_parse_search_query`):** сначала `split_prefix`; нет префикса → `None` (UNHANDLED). Триггер ищется в остатке по `Registry.FUNCTIONAL_COMMANDS["search"]`:
```python
def _parse_search_query(raw: str) -> str | None:
    tok, text = command_prefix.split_prefix(raw.strip())
    if tok is None:
        return None
    text = text.strip()
    m = _SEARCH_QUERY_RE.match(text)   # ^(?:найди|поищи|загугли)(?:[\s,:]+)(?:мне\s+|пожалуйста\s+)?(.+)$
    if m:
        return m.group(1).strip()
    return "" if command_registry.matches_group("search", text) else None
```
Триггер без тела («Бот, найди») → `""` → существующая фраза 5.2 (консьюм).

**youtube.py / web.py (`_parse`):** снять префикс; нет префикса → `(None, None)` (UNHANDLED); trigger/URL ищутся в остатке (`body`) по своим группам реестра. При `tok is not None` и совпавшем триггере, но отсутствии цели → **консьюм** нейтральной фразой (не пропуск к LLM, §7).

**checkup.py (`:53-58`, `_CHECKUP_TRIGGER_RE`):** split на два пути:
- **bare** `^чекап\b` — как сейчас (исключение);
- **prefixed** `префикс + (ты в порядке|живой?|чекни здоровье)` — новый regex по остатку.

**video_download.py (`:74-75`, `_TRIGGER_RE`):** перед матчем снять префикс; bare «скачай …» без обращения → UNHANDLED (новая семантика). Матч триггера — по остатку (`скачай|загрузи|стяни`), callback-ветки (`vdv:`/`vd:`) не трогаются. `спизди`/`скачать` из реестра убраны (F6-U1).

## 6. Приоритет роутера и «не в LLM» (без изменения порядка `bot.py`)

Порядок роутеров `bot.py:641-666` **не меняется** (0d search / 0e youtube / 0f web / 0g checkup идут ДО 0h direct_chat). Точка конфликта — **download (4e, ПОСЛЕ 0h)** и отключённые модули: `Бот, скачай`/`Олег, скачай` матчится бот-триггером/именем в direct_chat и был бы съеден LLM.

**Решение — yield в direct_chat (аддитивно, без переноса роутеров):** в `direct_chat_handler` ПОСЛЕ `_is_direct_trigger`, ДО память-команд/`handle`:
```python
if command_prefix.is_functional_command(text):
    return UNHANDLED          # D49-пропагация: сообщение уходит ниже (0i..4e)
```
- search/youtube/web/checkup (0d–0g) доходят до direct_chat уже только при не-триггере, поэтому для них yield — no-op.
- download (4e) получает сообщение по пропагации и консьюмит.
- Триггер без цели: функциональный воркер **консьюмит** нейтральной фразой (search — 5.2; youtube/web — новый пул `COMMAND_NO_TARGET_PHRASES` в `services/smartmodule_phrases.py`, аддитивно; download — существующий `VD_NO_LINK_PHRASES`).

**F6-Q6 RESOLVED:** переиспользуем существующие `reactions.chat_botword_pattern`/`flags.direct_chat_botword_enabled`; новый паттерн-ключ не вводим.

## 7. direct_chat: имя-триггер и отключение дефолтных (точный)

`handlers/direct_chat.py:147-165` (`_is_direct_trigger`):
```python
persona_on = hot.get("flags.persona_enabled", settings.PERSONA_ENABLED)
cached_name = str(bot_persona.get_cached_global_name() or "").strip()
name_set = bool(cached_name)
# 1) имя-триггер (со склонениями; гейт persona_on сохраняется — legacy 10.14)
if persona_on and name_set:
    if command_prefix.name_mentioned(text):
        return True
# 2) keyword-ветка «бот»: активна, только если НЕ (persona_on AND name_set)
if (not (persona_on and name_set)) and \
        hot.get("flags.direct_chat_botword_enabled", settings.DIRECT_CHAT_BOTWORD_ENABLED) \
        and _BOTWORD_RE.search(text):
    if message.from_user.id in _BOTWORD_EXCLUDED_USER_IDS:
        return False
    return True
return False
```
- Reply/mention/@username (`:133-146`) остаются первыми и неизменными.
- `_PEER_PREFIX_RE` у память-команд расширяется именем персоны (склонения) — «Олег, запомни …» работает; иначе — без изменений.

## 8. Границы (что НЕ входит)

- **F6-Q5 RESOLVED (итерация 2):** в скоуп входят **search, youtube, web, checkup, download** (UPD §2, скачай/загрузи/стяни теперь обязаны требовать обращение). `чекап`/`фактчек` — исключения (bare). `/summary`, голосовые, callback-кнопки — без изменений.
- Список триггеров — ровно §3 (F6-U1); новых «сверх канона» не добавляем.

## 9. Точки изменения (file:line, HEAD `798e044`)

| # | Файл:строка | Изменение |
|---|---|---|
| 1 | `services/command_registry.py` (новый) | Канон-реестр §3, `matches`, `FUNCTIONAL_COMMANDS`, `BARE_COMMANDS`. |
| 2 | `services/command_prefix.py` (новый) | `active_name`, `command_prefix_tokens`, `split_prefix`, `name_mentioned`, `is_functional_command`. |
| 3 | `handlers/search.py:57-101` | Снятие префикса; матч по `search`-группе. |
| 4 | `handlers/youtube.py:120-215` | Снятие префикса; `_YOUTUBE_TRIGGERS` = `youtube`-группа; консьюм без URL. |
| 5 | `handlers/web.py:52-96` | Снятие префикса; `_WEB_TRIGGERS` = `web`-группа; консьюм без URL. |
| 6 | `handlers/checkup.py:53-80` | bare `чекап` + prefixed `ты в порядке`/`живой?`/`чекни здоровье`; убрать `живой собака`. |
| 7 | `handlers/video_download.py:74-75,212-214` | Снятие префикса перед `_TRIGGER_RE`. |
| 8 | `handlers/direct_chat.py:128-165,317-322` | Отключение ботвордов при имени; `is_functional_command`-yield; имя в `_PEER_PREFIX_RE`. |
| 9 | `services/smartmodule_phrases.py` (аддитивно) | `COMMAND_NO_TARGET_PHRASES` (youtube/web без цели). |
| 10 | `bot.py:641-666` | **Не менять** порядок; DI не требуется (helper читает кэш напрямую). |

**Не трогать:** `_BOTWORD_EXCLUDED_USER_IDS`, reply/mention/`@username`-ветки, callback `vdv:`/`vd:`, `media/`/`.env`.

## 10. Тест-план

Новый `tests/test_command_registry_round1015.py`:
1. `split_prefix`: пустое имя → «Бот, загугли»/«бот загугли»/«бот: загугли»/«ботик, найди» ок; имя «Олег» → «Олег, загугли»/«олега загугли»/«Олегу, найди» ок; «работа загугли»/«ботва загугли» — НЕ ок; имя «И» (len<3) — без склонений.
2. Реестр: `matches` знает ровно 17 триггеров; `чекап`/`фактчек` — вне `FUNCTIONAL_COMMANDS`; F6-U1-алиасы (`перескажи видос`, `пульс бота`, `живой собака`) — НЕ матчатся.
3. search: «Олег, загугли X» → тело «X»; «загугли X» → `None`; «Бот, найди» → `""`.
4. youtube/web: «Олег, поясни за видос <url>» parses; «Олег, поясни за видос» → консьюм `COMMAND_NO_TARGET_PHRASES`; без префикса → UNHANDLED.
5. checkup: «чекап» → bare-триггер; «Олег, ты в порядке» → prefixed; «живой»/«живой собака» → НЕ триггер; «Олег, чекни здоровье» → prefixed.
6. download: «Олег, скачай <url>» → триггер; «скачай <url>» без обращения → UNHANDLED.
7. direct_chat: имя «Олег» → «эй, бот» = False (дефолты off), «Олег, привет» = True, «Олега, привет» = True; пустое имя → «эй, бот» = True; «Олег, скачай <url>» → `_is_direct_trigger` True, но handler отдаёт UNHANDLED (yield).
8. Приоритет: «Олег, загугли X» консьюмится search, direct_chat/LLM не вызываются (порядок 0d < 0h; интеграционный тест с моками).

**Обновляемые тесты (обоснование — bare-триггеры больше не валидны):** `tests/test_smartsearch_handlers.py`, `tests/test_youtube_handlers.py`, `tests/test_web_handlers.py`, `tests/test_checkup*`, `tests/test_video_download*`, `tests/test_epic72_gates.py:69`, `tests/test_direct_chat.py:2994-3010` — добавить префикс «Бот, » в позитивные кейсы; кейсы с непустым именем — `monkeypatch` `get_cached_global_name`/`flags.persona_enabled`.

**Гейты:** полный `pytest` 0 failed (фокус search/youtube/web/checkup/download/direct_chat/epic72); каталог-пин **435/406/411/90/88/19** (Δ=0); R17-скан; `git diff --check`; русский commit.

## 11. Каталог-Δ и rollout

- **Δ = 0** (флаг `flags.command_prefix_enabled` НЕ вводится): REGISTRY **435**, Settings **406**, categorized **411**, GROUPS **90**, mapped **88**, TAB_RULES **19**.
- **Progressive delivery неприменим** (нет рубильника). Мягкий переход обеспечивается пустым глобальным именем; откат = `git revert` + очистка Имени.
- Мониторинг: логи `[smartsearch]/[web]/[youtube]/[checkup]/[videodl] triggered` vs доля LLM-ответов direct_chat; всплеск «нет цели» — сигнал о ложных срабатываниях.

## 12. Открытые вопросы → решения

- **F6-Q1** per-chat имя: только глобальный sync-кэш; per-chat — вне скоупа.
- **F6-Q2** склонения: эвристический список окончаний; имена <3 симв. — без склонений.
- **F6-Q3 (revision)** отключение дефолтов: при `persona_enabled AND name_set`; флага нет.
- **F6-Q4** reply/mention/@username — без префикса, приоритетнее.
- **F6-Q5 (revision)** скоуп: search/youtube/web/checkup/download; `чекап`/`фактчек` — bare-исключения.
- **F6-Q6** переиспользуем существующие botword-ключ/паттерн.

## 13. Риски

| Риск | Митигация |
|---|---|
| Регресс живых чатов с непустым именем (дефолты off без рубильника) | Мягкий переход: пустой глобальный сид; откат `git revert` + очистка Имени; пред-деплой чек-лист владельцу. |
| Bare-триггеры перестают работать | Осознанная семантика фичи; синхронная правка тестов; гайд F7. |
| `Бот/Олег, скачай` съедается direct_chat | `is_functional_command`-yield (UNHANDLED) → пропагация до 4e; тест на приоритет. |
| F6-U1 снятые алиасы (`пульс бота`, `как сервак`, `перескажи видос`) | Зафиксировано как решение; вернуть «тихими» алиасами при возражении владельца. |
| Ложные срабатывания префикса («ботва», «работа») | `(?![0-9a-zа-яё_])` после токена + `_SEP` + начало строки. |
| Склонения ловят лишнее | Только `len(name) ≥ 3`; начало строки + границы. |

## 14. Критерии приёмки (DoD)

- [x] Канонический реестр §3 (17 prefixed + `чекап`/`фактчек` bare) захардкожен и покрыт тестом.
- [x] Имя не задано → «Бот, загугли» работает; дефолтные ботворды работают.
- [x] Имя задано → «Олег, загугли» работает; `бот`/`ботик`/`ботяра` не триггерят обычный ответ; склонения учтены.
- [x] Функциональная команда (в т.ч. `скачай`/`загрузи`/`стяни` и триггер без цели) перехватывается воркером и НЕ уходит в LLM.
- [x] Порядок роутеров `bot.py` не изменён; `чекап`/`фактчек` остаются bare.
- [x] Полный `pytest` 0 failed; каталог 435/406/411/90/88/19.

## 15. Инварианты

Порядок роутеров `bot.py` не менять (только DI-kwargs при необходимости), R16/R17, sync-путь без блокирующих PG, `media/`/`.env` не трогать, каталог Δ=0 (пин-тесты не правятся).
