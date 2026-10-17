# REVIEW-STYLE-AWAIT — независимая проверка фикса `68cd05b2` (SOUL-1 / 2.58.86 style-await)

| Поле | Значение |
|---|---|
| Коммит | `68cd05b2f2f0082b9dceb5a867285d47b09143b0` (master; `services/style_policy.py` +4/−1, `tests/test_soul1_style_policy.py` +67) |
| Вердикт | **Approved** — await-фикс корректен, инверсия RED→GREEN воспроизведена, числа и bounded-скан подтверждены |

## 1. Состав и корректность фикса

- Дифф — ровно два файла, ничего лишнего: в `save_policy_document` (global-ветка) `target.set(...)` → `await target.set(...)` + коммент со ссылкой на контракт; в тестах — новый строгий двойник + регрессионный тест.
- **Контракт подтверждён:** `ConfigCache.set` — `async def set(...)` (`services/config_cache.py:681`), апсерт PG `bot_settings` + in-memory под `asyncio.Lock`. Без await тело корутины не исполняется вовсе → ни PG, ни in-memory (ровно прод-симптом: `applied=true`, ключа нет).
- Чат-ветка не задета: там уже `await set_root(...)`; исключения не менялись (`except Exception → applied=False, reason=save_error`); стиль/коммент в конвенции файла.

## 2. Инверсия (изолированный worktree на `68cd05b2`)

- Базлайн: новый тест **GREEN** (1 passed).
- Убрал `await` → **RED** ровно по персистентности: `assert stored is not None` («глобальный документ не персистился (set без await?)»); при этом `applied is True / scope=global / revision=1` уже прошли — т.е. тест ловит именно класс «applied без записи», а не случайный симптом. Вернул `await` → **GREEN** (1 passed); worktree в scratch удалён после проверки.
- **Строгость `_StrictAsyncCache`:** `set` — `async def` (значение попадает в `values` и `writes` только при реальном await). Старый `FakeHot.set` (`tests/test_soul1_style_policy.py:48`) — **синхронный**, и такую ошибку не видит (обоснованно в докстринге). Ассерты — на наблюдаемое: `applied/scope/revision`, `stored`, `cache.writes`, отсутствие RuntimeWarning «never awaited», read-back через `effective_policy_sync(hot.get(...))` (правила видны, `source=global`), второй save без явного cache → `revision=2` и `history[0].revision=1`. Подгонки под реализацию нет.

## 3. Числа (мои прогоны)

| Прогон | Результат |
|---|---|
| `tests/test_soul1_style_policy.py` | **61 passed** |
| `tests/test_soul1_*.py` (30 файлов) | **600 passed** |
| focused (style_policy/style_payload/style_repetition/w6_speech_ui/hot_config/config_cache) | **155 passed** |
| `tools/gen_param_registry_round1025.py --check` (read-only) | `CHECK OK: реестр 575 == REGISTRY…` EXIT 0 |

## 4. Bounded-скан (других забытых await нет)

- Все `.set(` на cache/config-объектах в `services/**` и `web/**`: **24 — все awaited**; не-awaited cache-like `.set(` — **0**; cache-`.upsert/.store` — **0**.
- Широкий скан всех не-awaited `.set(` в services/web: 6 находок — только `threading.Event.set()`/`ContextVar.set()` (sync по природе): `_telemetry_stop`, `_watchdog_stop`, `event`, `_RUN_FRAME`, `_current_priority`, `_turn_text_replied`. Класс «забытый await» больше нигде не встречается.

## Итог

Фикс точечный и в правильном слое (единственный путь global-save через ConfigCache), регресс защищён durable-тестом с маркером `TEST-LIFECYCLE: REGRESSION owner=SOUL-1/2.58.86-style-await`; инверсия подтверждает, что тест падает на реальном дефекте и зеленеет на фиксе. Замечаний нет.
