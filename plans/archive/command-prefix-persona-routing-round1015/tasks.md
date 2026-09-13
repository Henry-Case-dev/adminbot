# Фича F6 — `command-prefix-persona-routing-round1015` (Префиксы команд, имя личности, приоритеты)

> **Статус: ✅ COMPLETED** (Step 4 @Builder, 14.09.2026). T-1593…T-1600 выполнены; гейты T-1601/T-1602 — за @Reviewer/@PM. pytest **5694 passed / 0 failed**; каталог Δ=0 (435/406/411/90/88/19). Коммит не делался (по указанию раунда).
> **Раунд:** 10.15. **Нумерация:** T-1593…T-1602 (продолжает F5 T-1592).
> **Тип:** backend (routing). **Приоритет:** **P0** — **главный регресс-риск раунда**.
> **Зависимости:** от F1–F5 не зависит; `flags.persona_enabled` из 10.14 — контекст совместимости.
> **Конфликт файлов:** `handlers/search.py`, `handlers/youtube.py`, `handlers/web.py`, `handlers/checkup.py`, `handlers/video_download.py`, `handlers/direct_chat.py`, `services/smartmodule_phrases.py`; `bot.py` — **только DI-kwargs, порядок роутеров не трогать**.
> **ТЗ:** `plans/current_task.md`, раздел **6** + UPD §1-2 (строки 79-125).
> **Эпик:** `Epic: Багфиксы Графа памяти, Воркера Сна и Ностальгии round1015`.
> **Baseline:** HEAD `798e044`; pytest **5589 passed / 0 failed**; каталог **435/90/406/411/88/19**.

## 0. Цель

Функциональные команды без префикса дают ложные срабатывания. Нужно: обязательный динамический префикс (из `active_persona.name` или «Бот»), отключение дефолтных ботвордов при заданном имени, наивысший приоритет функциональных команд над LLM. **Без флага-рубильника** — триггер = непустое Имя.

**Текущее состояние (Step 0):**
- Триггеры без префикса: `search.py:57-65`; `youtube.py:120-123`/`:171-174`; `web.py:52-70`; `checkup.py:53-58`; `video_download.py:74-75`.
- Порядок `bot.py:641-666`: search(0d)/youtube(0e)/web(0f)/checkup(0g) ДО direct_chat(0h); download — **4e ПОСЛЕ** direct_chat (`bot.py:736`).
- Имя-триггер direct_chat: `direct_chat.py:147-155`; ботворды `:156-164`.
- Persona-кэш: `services/bot_persona.py:362-379`.

## 1. Требования (ТЗ §6 + UPD §1-2)

- [x] **Отказ от флага:** триггер системы — непустое поле Имя; «Бот, », если пусто.
- [x] **Точный реестр 17** (§3 спеки) + **исключения** `чекап`/`фактчек` (одним словом).
- [x] **Интеграция с Именем:** префикс команд и триггер ответа динамически из `active_persona.name`; при имени дефолтные `бот/ботик/ботяра` полностью отключаются.
- [x] **Приоритет роутера:** Префикс+Триггер перехватывается воркером и НЕ уходит в LLM.

## 2. Целевые модули (`file:line` на HEAD `798e044`)

- `handlers/search.py:57-101`; `handlers/youtube.py:120-215`; `handlers/web.py:52-96`.
- `handlers/checkup.py:53-80`; `handlers/video_download.py:74-75,208-237`.
- `handlers/direct_chat.py:128-165,317-322`; `services/smartmodule_phrases.py`.
- `bot.py:641-666` (не менять порядок).
- Тесты: `tests/test_*search*`, `tests/test_*youtube*`, `tests/test_*web*`, `tests/test_checkup*`, `tests/test_video_download*`, `tests/test_epic72_gates.py:69`, `tests/test_direct_chat.py:2994-3010`; новый `tests/test_command_registry_round1015.py`.

## 3. Инварианты (constraints)

- **⚠️ ГЛАВНЫЙ РЕГРЕСС-РИСК.** Отключение дефолтов при имени и обязательный префикс ломают bare-кейсы. **Мягкий переход** — пустой глобальный сид; обратимость — очистка Имени.
- **Порядок роутеров `bot.py` НЕ менять.** Приоритет download (4e) — через `is_functional_command`-yield (UNHANDLED) в direct_chat.
- Функциональные хендлеры без префикса → **UNHANDLED** (совместимость с observer/пропагацией).
- R16, R17, sync-путь без блокирующих PG (`get_cached_global_name()`).
- Каталог-инварианты **435/90/406/411/88/19** — **Δ=0** (ключи не вводить).
- `media/`/`.env` не трогать.
- **Ревью-гейты:** полный `pytest` 0 регрессий, `node --check web/app.js`, пин-тесты каталога, R17-скан, русские commits.

## 4. Зависимости

- **Вверх:** нет (опирается на `flags.persona_enabled`/`get_cached_global_name` из 10.14).
- **Вниз:** **F7** (гайд) описывает реестр/имена; **D** (hybrid-tool-calling) опирается на fast-track приоритет.

## 5. Definition of Done

- [x] Канонический реестр §3 захардкожен (17 + 2 bare) и покрыт тестом.
- [x] Пустое имя → `Бот, загугли`; дефолтные ботворды работают.
- [x] Имя задано → `Олег, загугли`; `бот/ботик/ботяра` не триггерят; склонения учтены.
- [x] Функциональная команда (в т.ч. `скачай/загрузи/стяни`, триггер без цели) НЕ уходит в LLM.
- [x] Полный `pytest` **0 failed**; каталог Δ=0.

## 6. Чек-лист задач

- [x] **T-1593 (@Architect, гейт):** обновлённая спека/ADR — отказ от флага, реестр 17+2, прямой алгоритм снятия префикса, yield-механика для download, стратегия тестов. *(итерация 2 выполнена)*
- [x] **T-1594 (@Builder):** `services/command_registry.py` (канон §3) + `services/command_prefix.py` (`active_name`, `command_prefix_tokens`, `split_prefix`, `name_mentioned`, `is_functional_command`).
- [x] **T-1595 (@Builder):** обязательный префикс в `search.py`, `youtube.py`, `web.py`; нет префикса → UNHANDLED; консьюм без цели (новый `COMMAND_NO_TARGET_PHRASES`).
- [x] **T-1596 (@Builder):** `checkup.py` — bare `чекап` + prefixed `ты в порядке`/`живой?`/`чекни здоровье`; удалить `живой собака`.
- [x] **T-1597 (@Builder):** `video_download.py` — снятие префикса; bare «скачай …» → UNHANDLED; callback-ветки не трогать.
- [x] **T-1598 (@Builder):** `direct_chat.py` — отключение ботвордов при имени; `is_functional_command`-yield; имя в `_PEER_PREFIX_RE`.
- [x] **T-1599 (@Builder):** новый `tests/test_command_registry_round1015.py` (кейсы §10 спеки) + правка существующих handler-тестов под префикс (обоснование — новая семантика).
- [x] **T-1600 (@Builder):** гейты: полный `pytest` **0 failed** (5694 passed), каталог 435/406/411/90/88/19, `node --check web/app.js`, R17-скан, `git diff --check`. *(русский commit не выполнялся — по указанию раунда «НЕ коммить»)*
- [ ] **T-1601 (@PM/@Reviewer, гейт):** сверка DoD, отдельное ревью регресс-риска (живые чаты, F6-U1-алиасы), подтверждение `file:line`.
- [ ] **T-1602 (@PM/@DevOps, гейт):** пред-деплой чек-лист (пустое vs непустое Имя), пост-деплой мониторинг маршрутизации, план отката (`git revert` + очистка Имени).

## 7. Открытые вопросы (@Architect → владелец)

- **F6-Q1…Q6 — RESOLVED** (см. spec §12). Новых Human Gate нет.

## 8. Feature flag / progressive delivery

- **Feature flag не требуется** (решение владельца, UPD §1). Мягкий переход — пустой глобальный дефолт; откат = `git revert` + очистка Имени.
- **Progressive delivery неприменим.** Мониторинг — по логам `triggered` vs LLM.
