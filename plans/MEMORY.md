# MEMORY.md — AdminBot

> **Версия:** v2.21.0 DEPLOYED (Epic 23, коммит `756d237`)
> **Дата:** 2026-08-16
> **Обновление:** 2026-08-16 — **Epic 23 «Правка danger-словаря» DONE & DEPLOYED ✅ (v2.21.0, коммит `756d237`): T-169..T-172 DONE (включая деплойные подзадачи E..G), 672 теста PASS (621+51), ревью 2 раунда APPROVED. Деплой: git pull `0c74220..756d237` (9 файлов), .env DANGER_WORDS пустой (дефолты активны), проверка «118 17» совпала, сервис active (running) PID 917681, логи чистые.**
> **Статус:** Epics 1–23 ALL DEPLOYED ✅ (v2.21.0, `756d237`). Epic 23 «Правка danger-словаря» DONE & DEPLOYED ✅ — словарь 118 слов + 17 фраз (135 паттернов) в продакшене.
> **Текущий коммит:** `756d237` (feat(danger): Epic 23 — точная настройка danger-словаря (v2.21.0)) на master, пуш в origin (github.com/Henry-Case-dev/adminbot.git).
> **Сервер:** 198.46.175.136:/var/www/admin_bot, systemctl active (running), PID 917681, логи чистые (Bot started, listening...).

---

## 🔍 Context Sync Summary (2026-08-15) — Epic 22 DONE & DEPLOYED, v2.20.0 в продакшене

| Area | Status | Notes |
|------|--------|-------|
| **Epics 1-21** | ✅ DEPLOYED | 160+ задач T-001–T-162 + T2/T3/T4 + Epic 18 A/B/C. v2.19.0 (commit c683903) был в продакшене до 2026-08-15. |
| **Epic 22** | ✅ DONE & DEPLOYED | «Гонка функций и точность триггеров» — PM-решения D51–D54, T-163..T-167 (включая D) завершены. 621 тест PASS (+35 новых). Коммит `1dbb6da`, пуш, деплой. Прод v2.20.0. |
| **Review (current)** | ✅ APPROVED | 621 tests pass / 0 failed. 3 раунда ревью, все замечания закрыты (README v2.20.0/621, планы IMPLEMENTED, board «In Review»). |
| **Сервер** | ✅ ACTIVE | 198.46.175.136:/var/www/admin_bot. systemctl: active (running), PID 914116 (был 699945). Логи чистые (Bot started, listening...). HEAD=1dbb6da. |

---

## 📁 Политика media/ (по указанию пользователя, 2026-08-16) — ОБЯЗАТЕЛЬНА К ИСПОЛНЕНИЮ

> **Всё, что добавляется или удаляется в папке `media/` (`media/common/danger`, `media/olya/cringe`, `media/slavik_random` и т.п.), — делается СОЗНАТЕЛЬНО и СПЕЦИАЛЬНО для загрузки на сервер и дальнейшего использования ботом.**

- Media-файлы **НЕ являются случайными артефактами**: их НЕЛЬЗЯ исключать из коммитов как мусор, НЕЛЬЗЯ добавлять в `.gitignore`, НЕЛЬЗЯ удалять без явного указания пользователя.
- ❌ Рекомендация «добавить `danger_drone.mp4` в `.gitignore`» была **ОШИБОЧНОЙ и ОТМЕНЯЕТСЯ**.
- ✅ `media/common/danger/danger_drone.mp4` — **16-й файл danger-пула**, добавлен намеренно: его нужно **закоммитить и задеплоить**. Пул danger-медиа используется сервисом danger-слов (DangerWordFilter → CommonRelay), media_picker выбирает файлы из папки автоматически — дополнительный код не требуется.

---

## 🚧 Epic 22: Гонка функций и точность триггеров — v2.20.0 (DONE & DEPLOYED, 2026-08-15)

> **Цель:** Устранить гонку ответов Славика (приветствие vs dead page vs «пошёл нахуй»),
> сделать триггеры точнее: Olya — только SaveAsBot-видео, mimic — не передразнивать репосты,
> PostPicker — не выбирать пост, отправленный в предыдущий раз.
> **Статус:** DONE & DEPLOYED ✅ — T-163..T-167 (A/B/C/D) завершены, ревью 3 раунда (замечания закрыты), 621 тест PASS, 0 регрессий.
> Коммит `1dbb6da` на master, пуш в origin, деплой на 198.46.175.136:/var/www/admin_bot (git pull c683903..1dbb6da, 21 файл, +1778/-224, systemctl restart OK, PID 914116). Прод v2.20.0.
> **Target (достигнут):** v2.20.0, 621 тест (586 baseline + 35 новых), 0 регрессий.

### PM-решения D51–D54

| # | Решение | Задача | Суть |
|---|---------|--------|------|
| **D51** | Olya SaveAsBot-only | T-163 | Логика **ИЛИ** сохраняется (caption ИЛИ репост из `OLYA_SAVEASBOT_CHANNEL_IDS`=523131145). Дефолт `OLYA_ALWAYS_SEND` True→**False**. ⚠️ prod .env может содержать `OLYA_ALWAYS_SEND=True`. |
| **D52** | Mimic forwards gate | T-164 | Единый параметр **`MIMIC_FORWARDS_ENABLED=False`** для ОБОИХ mimic-механизмов (`handlers/common.py::mimic_handler`, `handlers/slavik.py::_slavik_mimic_should_trigger`). `forward_origin is not None` + off → mimic пропущен. |
| **D53** | Slavik race fix | T-165 | `DEAD_PAGE_POST_ON_JOIN=False` (join → только «ДОЛБОЕБ ВЕРНУЛСЯ»); dead_page_trigger — только репосты Славы (`UserIdFilter`, is_present-гейт убран); catch-all Branch 0 гейт: d_pages-репост → `UNHANDLED`. Приоритет: приветствие > dead page > «пошёл нахуй». |
| **D54** | PostPicker last-sent | T-166 | Ключ `channel_state` **`dead_page_last_sent:{chat_id}`** (≠ `last_known_message_id`). last_sent исключается из forward/sequential/random веток; fallback-повтор при единственном посте; запись primary msg_id после успеха. Фикс бага «почти всегда id 3». |

### Задачи Epic 22

| Task | Название | Компоненты | Статус |
|------|----------|-----------|--------|
| **T-163** | Olya: только SaveAsBot-видео (D51) | config/settings.py, .env.example, tests/test_olya.py | ✅ DONE (APPROVED) |
| **T-164** | Mimic: не передразнивать репосты (D52) | config/settings.py, handlers/common.py, handlers/slavik.py | ✅ DONE (APPROVED) |
| **T-165** | Славик: приоритет приветствия + dead page на репосты Славы (D53) | handlers/dead_page_trigger.py, handlers/slavik.py, tests/test_slavik_priority.py (NEW) | ✅ DONE (APPROVED) |
| **T-166** | PostPicker: не выбирать last-sent пост (D54) | services/database.py, services/dead_page_relay.py | ✅ DONE (APPROVED) |
| **T-167** | README (ироничный тон), полный pytest (621), conventional commit на русском | README/ARCHITECTURE/MEMORY | ✅ A/B/C/D DONE (APPROVED + DEPLOYED, коммит `1dbb6da`) |

### Ключевой API-контекст (Section 30.2)

- aiogram 3.x `message.forward_origin`: **None** для обычных сообщений, `MessageOriginChannel` для репостов из каналов (`origin.chat.id` — канал-источник); legacy `forward_from*` deprecated (Bot API 7.0).
- MagicMock gotcha: атрибуты автогенерируются и truthy — тестовые фабрики должны явно выставлять `msg.forward_origin = None`; гейты mock-safe через `isinstance`.
- `forwardMessage(s)` — `Bad Request: message to forward not found` = штатный признак отсутствующего пробного id → `continue`.

### Риски миграции (Section 30.9)

| # | Риск | Митигация |
|---|------|-----------|
| R1 | Prod `.env` с явными `OLYA_ALWAYS_SEND=True` / `DEAD_PAGE_POST_ON_JOIN=True` | Деплой-чеклист DevOps |
| R2 | Контракт `_try_forward_from_channel: bool → int\|None` | 9 assertion-строк в тестах обновляются в T-166 |
| R5 | Sequential scan «всегда id 3» | skip last_sent; при единственном посте — осознанный повтор |
| R7 | Миграция БД | Не нужна — переиспользуется `channel_state` |

### Результаты ревью — 3 раунда, APPROVED ✅

- 621 тест PASS / 0 failed (+35 новых: `tests/test_slavik_priority.py` NEW, классы `TestMimicForwardsGate`, `TestAntiRepeatLastSent` и др.).
- Флаки-тест `test_sequential_scan_finds_only_post` детерминирован патчем `random.randint` (side_effect [77..86], 25/25 PASS).
- Все замечания закрыты: README v2.20.0/621, статусы планов IMPLEMENTED, board «In Review», нумерация T-167 выровнена.
- Наблюдения ревьюера (не блокеры): README пишет «ДОЛБОЕВ» vs планы «ДОЛБОЕБ»; фактическая ветка — master.
- ✅ Деплой-чеклист DevOps выполнен (2026-08-15): prod `.env` → `DEAD_PAGE_POST_ON_JOIN=False` (True→False, бэкап `.env.bak.2026-08-15`); `OLYA_ALWAYS_SEND` и `MIMIC_FORWARDS_ENABLED` отсутствуют в .env — активны дефолты False.
- ❌→✅ `media/common/danger/danger_drone.mp4` — **ОТМЕНЕНО пользователем (2026-08-16):** рекомендация «добавить в `.gitignore`» была ошибочной. Файл добавлен НАМЕРЕННО (16-й файл danger-пула) → должен быть ЗАКОММИЧЕН и ЗАДЕПЛОЕН.

---

## ✅ Epic 23: Правка danger-словаря — v2.21.0 (DONE & DEPLOYED, 2026-08-16)

> **Цель:** Сократить и уточнить danger-словарь: убрать «шумные» секции, добавить фразовые шаблоны (shelter/атака), сохранить совместимость `{"matched_word"}`.
> **Статус (2026-08-16):** DONE & DEPLOYED ✅ — T-169..T-172 DONE (включая деплойные подзадачи E..G), **672 теста PASS** (621 baseline + 51 новых), ревью 2 раунда APPROVED. Деплой: git pull `0c74220..756d237` (9 файлов) на 198.46.175.136:/var/www/admin_bot; `.env` DANGER_WORDS пустой → дефолты активны; проверка «118 17» совпала; systemctl active (running) PID 917681; логи чистые. **Прод v2.21.0.**

### Факты реализации

| Параметр | Было | Стало |
|----------|------|-------|
| **DANGER_WORDS** | 191 словоформа | **118** (удалены Flight, Shelter, Атака/угроза, Падение/сбитие; добавлены хлопок/хлопки/хлопнуло/хлопнул) |
| **DANGER_PHRASES** | — | **17 фраз**: 10 shelter + 7 атака, longest-first |
| **Итого паттернов** | 191 | **135** (118 слов + 17 фраз) |

### Механика (D55–D58)

- `_build_phrase_patterns` в `DangerWordFilter` (filters/danger_word.py): фразы проверяются **ДО** слов, границы по краям фразы, `re.IGNORECASE`.
- Возврат `{"matched_word": ...}` **совместимый** — Telegram quote API не сломан.
- **Env-независимо:** дефолты в `filters/word_lists.py`; `DANGER_WORDS` env var — только опциональный override. Прод `.env` НЕ трогаем.
- Потребители: `war_alert` (роутер 4b) и `danger_handler` (роутер 4c) — единый словарь.

### Тесты — 672 PASS / 0 failed

- **672** = 621 baseline + 51 новых.
- Переписаны/добавлены: `TestDangerPhrases` (**42 кейса**), контрактный тест (**17 фраз**), негативы.
- Ревью: 2 раунда, APPROVED ✅ (2 фикса тестов выполнены дословно).

### Задачи Epic 23

| Task | Название | Статус |
|------|----------|--------|
| **T-169** | Правка DANGER_WORDS в filters/word_lists.py (191→118) | ✅ DONE + APPROVED |
| **T-170** | DANGER_PHRASES (17 фраз) в filters/word_lists.py | ✅ DONE + APPROVED |
| **T-171** | `_build_phrase_patterns` + тесты (TestDangerPhrases 42 кейса, контракт 17 фраз) | ✅ DONE + APPROVED |
| **T-172** | README/планы + коммит + деплой v2.21.0 | ✅ DONE & DEPLOYED (E..G закрыты, коммит `756d237`, PID 917681) |

---

## 🔍 Context Sync Summary (2026-08-03) — Epic 21 DEPLOYED ✅

| Area | Status | Notes |
|------|--------|-------|
| **Epics 1-20** | ✅ DEPLOYED | 130+ задач T-001–T-148 + T2/T3/T4 + Epic 18 A/B/C + Epic 19 + Epic 20. v2.18.0 в продакшене. |
| **Epic 21** | ✅ DEPLOYED | MIMIC propagation fix + Time-format cooldowns. 14 задач T-149–T-162. D49 + D50. Commit c683903. |
| **Review** | ✅ PASS | 586 tests pass. 0 failures. Zero regressions. |
| **Сервер** | ✅ ACTIVE | nik@198.46.175.136:/var/www/admin_bot. systemctl: active (running), PID 699945, 121.6M. |
| **DevOps (T-162)** | ✅ DEPLOYED | Commit c683903, push origin/master, server pull + restart successful. Zero errors in logs. |

---

## ✅ Epic 21: MIMIC Propagation Fix + Time-Format Cooldowns — v2.19.0 (DEPLOYED, 2026-08-03)

> **Цель:** Исправить propagation-блокировку в `alan_handler` (MIMIC не работал для Alan) и перевести все кулдауны на человекочитаемый time-format (1s/1m/1h/1d).
> **Статус:** DEPLOYED ✅ — все 14 задач T-149–T-162 выполнены и задеплоены в production. 586 тестов проходят.
> **Версия:** v2.19.0 (деплой на сервер выполнен).
> **Коммит:** `c683903` на master, пуш в origin/master.
> **Сервер:** nik@198.46.175.136:/var/www/admin_bot, PID 699945, active (running), 121.6M.

### Root Cause: alan_handler blocks propagation

```
Alan (138811255) пишет сообщение в чат
    ↓
alan_router (pos 3): UserIdFilter matches → alan_handler()
    → считает сообщение, возможно делает reply
    → implicit return None ← БЛОКИРУЕТ propagation
    ↓
common_router (pos 4c): НИКОГДА не получает события
    → mimic_handler НЕ срабатывает (MIMIC сломан для Alan)
    → danger_handler / otboy_handler тоже не получают
```

**SLAVIK_MIMIC НЕ затронут** — он изолирован в `slavik_router` (позиция 5), который получает события независимо от `alan_router`.

### Design Decisions — IMPLEMENTED

| # | Решение | Описание | Статус |
|---|---------|----------|--------|
| **D49** | return UNHANDLED в alan_handler | Добавить `from aiogram.dispatcher.event.bases import UNHANDLED` + `return UNHANDLED` в конце `alan_handler()` И в ранних return (строки 84, 89). 1 файл (`handlers/alan.py`), 3 строки изменения. | ✅ IMPLEMENTED |
| **D50** | Time-format cooldowns | Новые хелперы `_parse_duration()` и `_env_duration()` в `config/settings.py`. Поддерживаемые форматы: `1s`, `30s`, `1m`, `5m`, `1h`, `2h`, `1d`, `0`. Переименование 6 полей: `*_COOLDOWN_SECONDS` → `*_COOLDOWN`. Backward-compat через fallback для plain integer значений. | ✅ IMPLEMENTED |

### Cooldown Renames — COMPLETED

| Старое имя | Новое имя | Новый Default | Было |
|-----------|----------|---------------|------|
| `MIMIC_COOLDOWN_SECONDS` | `MIMIC_COOLDOWN` | `"1h"` (3600s) | `60.0` |
| `SLAVIK_MIMIC_COOLDOWN_SECONDS` | `SLAVIK_MIMIC_COOLDOWN` | `"60s"` (60s) | `60.0` |
| `COMMON_COOLDOWN_SECONDS` | `COMMON_COOLDOWN` | `"0"` (disabled) | `0` |
| `DEAD_PAGE_COOLDOWN_SECONDS` | `DEAD_PAGE_COOLDOWN` | `"10s"` (10s) | `10` |
| `DANGER_COOLDOWN_SECONDS` | `DANGER_COOLDOWN` | `"60s"` (60s) | `60.0` |
| `OLYA_COOLDOWN_SECONDS` | `OLYA_COOLDOWN` | `"60s"` (60s) | `60.0` |

### Tasks Epic 21 — IMPLEMENTED

| Task | Название | Компонент | Статус |
|------|----------|-----------|--------|
| **T-149** | MIMIC propagation fix — `return UNHANDLED` в `alan_handler` (3 места: line 84, 89, end) | `handlers/alan.py` | ✅ IMPLEMENTED |
| **T-150** | Создать `_parse_duration()` и `_env_duration()` хелперы | `config/settings.py` | ✅ IMPLEMENTED |
| **T-151** | Переименовать 6 cooldown полей в Settings dataclass | `config/settings.py` | ✅ IMPLEMENTED |
| **T-152** | Обновить `bot.py` — переименовать вызовы `settings.*_COOLDOWN` | `bot.py` | ✅ IMPLEMENTED |
| **T-153** | Обновить `handlers/slavik.py` — `SLAVIK_MIMIC_COOLDOWN` | `handlers/slavik.py` | ✅ IMPLEMENTED |
| **T-154** | Обновить `services/dead_page_relay.py` — `DEAD_PAGE_COOLDOWN` | `services/dead_page_relay.py` | ✅ IMPLEMENTED |
| **T-155** | Verify mimic_relay + common_relay — без внутренних изменений | `services/*.py` | ✅ IMPLEMENTED (verified, no changes) |
| **T-156** | Добавить тест UNHANDLED в `alan_handler` | `tests/test_alan.py` | ✅ IMPLEMENTED |
| **T-157** | Обновить `.env.example` — time-format defaults | `.env.example` | ✅ IMPLEMENTED |
| **T-158** | Создать `tests/test_duration.py` — 15 test cases | `tests/test_duration.py` (NEW) | ✅ IMPLEMENTED |
| **T-159** | Полный прогон тестов — 586 tests PASS, 0 failures | `pytest` | ✅ IMPLEMENTED |
| **T-160** | Обновить `README.md` — version v2.19.0, config table, 586 tests | `README.md` | ✅ IMPLEMENTED |
| **T-161** | Sync MEMORY.md — Epic 21 completion status | `plans/` | ✅ IMPLEMENTED |
| **T-162** | Commit, push, deploy | DevOps | ✅ DEPLOYED (commit c683903, server: PID 699945) |

### Reviewer Audit — 3 Issues Found, ALL FIXED

| # | Severity | Описание | Файл | Status |
|---|----------|----------|------|--------|
| **1** | HIGH | `.env` line 26: `DEAD_PAGE_COOLDOWN_SECONDS=0` → `DEAD_PAGE_COOLDOWN=0` (старое имя поля) | `.env` | ✅ FIXED |
| **2** | HIGH | `handlers/alan.py` lines 84, 89: Early returns `return` → `return UNHANDLED` (блокировали propagation на ранних выходах) | `handlers/alan.py` | ✅ FIXED |
| **3** | MEDIUM | `.env`: Missing new cooldown variables (COMMON_COOLDOWN, DANGER_COOLDOWN, MIMIC_COOLDOWN, SLAVIK_MIMIC_COOLDOWN, OLYA_COOLDOWN) | `.env` | ✅ FIXED |

### Affected Files — IMPLEMENTED

| Файл | Тип | Изменения |
|------|-----|-----------|
| `config/settings.py` | MODIFY | +2 хелпера (`_parse_duration`, `_env_duration`), 6 переименований полей, тип float→str |
| `handlers/alan.py` | MODIFY | +import UNHANDLED, +return UNHANDLED (3 строки: lines 84, 89, end) |
| `bot.py` | MODIFY | ~6 строк переименований `*_COOLDOWN_SECONDS` → `*_COOLDOWN` |
| `handlers/slavik.py` | MODIFY | 1 строка переименования `SLAVIK_MIMIC_COOLDOWN` |
| `services/dead_page_relay.py` | MODIFY | 2 строки переименования `DEAD_PAGE_COOLDOWN` |
| `services/mimic_relay.py` | VERIFIED | БЕЗ ИЗМЕНЕНИЙ — внутренние параметры `cooldown_seconds` не переименованы |
| `services/common_relay.py` | VERIFIED | БЕЗ ИЗМЕНЕНИЙ — внутренние параметры `cooldown_seconds`/`danger_cooldown_seconds` не переименованы |
| `.env.example` | MODIFY | 6 переменных переименованы с time-format значениями + комментарий |
| `.env` | MODIFY | Reviewer fixes: DEAD_PAGE_COOLDOWN + missing vars |
| `README.md` | MODIFY | v2.19.0, config table sync, 586 tests |
| `tests/test_alan.py` | MODIFY | +1 тест (UNHANDLED return) |
| `tests/test_duration.py` | **CREATE** | 15 тестов `_parse_duration` + `_env_duration` |

### Test Suite (586 total)

| Area | Count | Delta |
|------|-------|-------|
| Baseline (Epic 20 deployed) | 570 | — |
| Epic 21: test_alan.py (UNHANDLED) | +1 | T-156 |
| Epic 21: test_duration.py (NEW) | +15 | T-158 |
| **Total** | **586** | **+16 net** |

### Architectural Decisions Summary

| # | Решение | Описание | Статус |
|---|---------|----------|--------|
| **D49** | return UNHANDLED in alan_handler | 3 return paths updated (end + 2 early returns). Propagation restored. | ✅ IMPLEMENTED |
| **D50** | Time-format cooldowns | `_parse_duration`(s/m/h/d) + `_env_duration` with backward-compat. 6 fields renamed. | ✅ IMPLEMENTED |

---

## 📋 Project Overview

**AdminBot** — юмористический Telegram-бот для личного чата трёх друзей (Слава, Костик, Вася).  
Написан на **Python** с использованием **aiogram 3.x**. Работает через long-polling.

### Стек
| Компонент | Технология | Статус |
|-----------|-----------|--------|
| Рантайм | Python 3.x + asyncio | ✅ |
| Фреймворк | aiogram 3.7+ | ✅ |
| База данных | SQLite (local_database.db) | ✅ 5 таблиц, WAL mode |
| Конфигурация | .env + config/settings.py | ✅ Все настройки через env, time-format cooldowns |
| Тесты | pytest + pytest-asyncio | ✅ 672 теста PASS (v2.21.0 DEPLOYED, Epic 23; 621 baseline + 51 новых) |
| Документация | ARCHITECTURE.md, MEMORY.md | ✅ |
| Мониторинг | ✅ Sentry + Logtail | Error tracking + cloud logging via Better Stack |

### Пользователи чата

| Персона | User ID | Прозвище | Роутер |
|---------|--------|----------|--------|
| **Слава (Slavik)** | `479167456` | «Куча» | `handlers/slavik.py` |
| **Костик (Kostik)** | `350803143` | — | `handlers/kostik.py` |
| **Вася (Vasya)** | no ID | — | `handlers/vasya.py` |
| **@Alan_Z** | `138811255` | — | `handlers/alan.py` (F6 + F7v2) + `handlers/alan_greeting.py` (F7) |
| **Admin** | `5885953495` | — | `handlers/admin_commands.py` (Epic 9) |

---

## 🏗️ Key Architectural Decisions

### 1. Router Priority Order (КРИТИЧНО — v2.19.0)
```
0.  admin_commands_router (Command filters) — /deadpage, /alangreet
1.  ChatMemberUpdated (slava_presence_router) — F1
1b. ChatMemberUpdated (alan_greeting_router) — F7: Alan join → greeting video
2.  kostik_router (user_id=350803143)
3.  alan_router (user_id=138811255) + DB counter — F6 + F7v2 silence greeting
    → RETURNS UNHANDLED (D49) — propagation restored for Alan
4.  dead_page_router — Dead Page V2 trigger from @d_pages
4b. war_alert_router — F5v2: war keywords (Slava) + TargetChannelFilter repost detection
4c. common_router — F9/F10: otboy_handler + danger_handler + mimic_handler (ALL users, DUAL cooldown)
4d. olya_router — F11: Olya video trigger (user_id=834424825) + plain send media
5.  slavik_router (user_id=479167456) + middleware F3 + F4 + catch-all + slavik_mimic (F8)
6.  vasya_router (text filters, no user restriction)
```

### 2. Фичи (F1–F11)

| # | Фича | Реализация | Статус |
|---|------|------------|--------|
| **F1** | Детект возвращения Славы → «ДОЛБОЕБ ВЕРНУЛСЯ» | `handlers/slava_presence.py` | ✅ |
| **F2** | Dead Page V2: forwardMessage из @d_pages + fallback | `DeadPageRelay` + `DeadPageTrigger` | ✅ |
| **F3** | GIF каждые 5 сообщений Славы | `MessageCounterMiddleware` | ✅ |
| **F4** | «КУЧА» → «ДАЛБАЕБ» | `handlers/slavik.py` + `KuchaWordFilter` | ✅ |
| **F5v2** | War Words Alert: caption fix, 90+ keywords, TargetChannelFilter, random replies | `handlers/war_alert.py` | ✅ |
| **F6** | @Alan_Z → random reply каждые 10 сообщений | `handlers/alan.py` (returns UNHANDLED) | ✅ |
| **F7** | Alan join → random greeting video | `handlers/alan_greeting.py` | ✅ |
| **F7v2** | Alan silence greeting — "Леха проснулся" | `handlers/alan.py` (inlined, returns UNHANDLED) | ✅ |
| **F8** | slavic_na_litso.jpg — каждый N-й "пошёл нахуй" → фото | `handlers/slavik.py` | ✅ |
| **E9** | Admin test commands: /deadpage, /alangreet | `handlers/admin_commands.py` | ✅ |
| **F9** | Otboy Service — детект "отбой" → common/otboy/ media | `handlers/common.py` (otboy_handler) + `CommonRelay` | ✅ |
| **F10** | Danger Detection — 135+ keywords from word_lists.py | `handlers/common.py` (danger_handler) + `DangerWordFilter` + `CommonRelay` (dual cooldown) | ✅ |
| **F11** | Olya Service — видео от @ole4444444ka → cringe media | `handlers/olya.py` + `OlyaRelay` + `OlyaVideoFilter` | ✅ |

### 3. Database Schema (SQLite, 5 tables)

| Таблица | Назначение | Ключевые колонки |
|---------|-----------|-----------------|
| `user_presence` | Присутствие пользователя (F1, F2) | `user_id`, `chat_id`, `is_present` |
| `message_counters` | Счётчик сообщений (F3, F6) | `chat_id`, `user_id`, `count` |
| `dead_page_posts` | Учёт dead-page постов (F2 V2) | `chat_id`, `slot`, `timestamp` |
| `channel_state` | Ключ-значение (F2 V2, F7v2) | `key` (TEXT PK), `value` (TEXT) |
| `relay_album_map` | Трекинг media_group_id для альбомов (Epic 14) | `message_id` (INTEGER PK), `media_group_id` (TEXT, INDEXED) |

### 4. Config (env-configurable via settings.py, TIME-FORMAT v2.19.0)

| Переменная | По умолчанию | Назначение |
|-----------|-------------|------------|
| `API_TOKEN` | (required) | Telegram Bot Token |
| `SLAVIK_USER_ID` | `479167456` | Slava's Telegram user ID |
| `KOSTIK_USER_ID` | `350803143` | Kostik's Telegram user ID |
| `ALAN_USER_ID` | `138811255` | Alan's Telegram user ID |
| `ALAN_SILENCE_GREETING_HOURS` | `6.0` | F7v2: hours of silence before greeting (prod=2) |
| `ADMIN_USER_ID` | `5885953495` | Admin user ID (Epic 9) |
| `GIF_INTERVAL` | `5` | Send GIF every N messages |
| `GIF_PATH` | `media/slavic_chlen.mp4` | GIF file path |
| `WAR_CHANNEL_IDS` | `1654872411` | War repost detection channel IDs (F5v2) |
| `WAR_CHANNEL_USERNAMES` | `` | War repost detection channel usernames (F5v2) |
| `WAR_REPLIES` | `` | Custom war reply phrases (F5v2) |
| `SLIVIC_NA_LITSO_INTERVAL` | `10` | F8: каждый N-й "пошёл нахуй" → фото |
| `MIMIC_COOLDOWN` | `1h` | F6: MIMIC cooldown (time-format: 1s/1m/1h/1d) ✅ v2.19.0 |
| `SLAVIK_MIMIC_COOLDOWN` | `60s` | F8: Slavik MIMIC cooldown (time-format) ✅ v2.19.0 |
| `COMMON_COOLDOWN` | `0` | F9/F10: shared cooldown for common sub-services (0=off, time-format) ✅ v2.19.0 |
| `DANGER_COOLDOWN` | `60s` | F10: danger-specific cooldown (dual-layer, time-format) ✅ v2.19.0 |
| `DEAD_PAGE_COOLDOWN` | `10s` | F2 V2: dead page relay cooldown (time-format) ✅ v2.19.0 |
| `OLYA_COOLDOWN` | `60s` | F11: Olya service cooldown (time-format) ✅ v2.19.0 |
| `COMMON_MEDIA_BASE` | `media/common` | F9/F10: base directory for common/otboy/ and common/danger/ |
| `DANGER_WORDS` | `(135+ keywords)` | F10: comma-separated danger keywords (единый источник: filters/word_lists.py) |
| `OLYA_ENABLED` | `True` | F11: enable/disable Olya Service (0=off) |
| `OLYA_USER_ID` | `834424825` | F11: Olya's Telegram user ID (@ole4444444ka) |
| `OLYA_MEDIA_BASE` | `media/olya/cringe` | F11: media directory for Olya cringe files |
| `OLYA_CAPTION_TEXT` | `(SaveAsBot text)` | F11: key caption text for Condition A detection |
| `OLYA_SAVEASBOT_CHANNEL_IDS` | `523131145` | F11: channel IDs for SaveAsBot repost detection |
| `OLYA_ALWAYS_SEND` | `False` | F11: always send media regardless of caption/repost match ✅ v2.20.0 IMPLEMENTED (Epic 22 D51: дефолт True→False) |
| `MIMIC_FORWARDS_ENABLED` | `False` | Epic 22 D52 (NEW) ✅ v2.20.0 IMPLEMENTED: mimic только обычные сообщения; True = включая репосты (forward_origin is not None) |
| `DEAD_PAGE_POST_ON_JOIN` | `False` | Epic 22 D53 ✅ v2.20.0 IMPLEMENTED: при входе только «ДОЛБОЕБ ВЕРНУЛСЯ» (dead page на join выключен) |
| `dead_page_last_sent:{chat_id}` | — (channel_state) | Epic 22 D54 ✅ v2.20.0 IMPLEMENTED: anti-repeat ключ БД — PostPicker не выбирает последний отправленный пост |

---

## Previous Completed Epics

| Version | Date | Epic | Tasks | Tests |
|---------|------|------|-------|-------|
| v1.0.0 | 2026-07-07 | Epic 1-4 | T-001–T-017 | 130 |
| v2.0.0 | 2026-07-12 | Epic 6 (Dead Page V2) | T-018–T-028 | 137 |
| v2.1.0 | 2026-07-12 | Epic 7 (Monitoring) | T-029–T-037 | 146 |
| v2.2.0 | 2026-07-13 | Epic 8 (F7 Alan Greeting) | T-038–T-045 | 164 |
| v2.3.0 | 2026-07-14 | Bugfixes T-046–T-047 | T-046–T-047 | 32 |
| v2.4.0 | 2026-07-14 | Epic 9 (Admin Commands) | T-048–T-051 | 181 |
| v2.5.0 | 2026-07-14 | T-052 (Sequential Scan) | T-052 | 185 |
| v2.6.0 | 2026-07-15 | T-053 (Propagation Fix) | T-053 | 190 |
| v2.7.0 | 2026-07-16 | Epic 10 (F5v2 War Words) | T-054–T-063 | 252 |
| v2.8.0 | 2026-07-18 | Epic 11 (F7v2) | T-064–T-077 | 271 |
| v2.9.2 | 2026-07-26 | Epic 12 (F8) | T-078–T-083 | 280 |
| v2.10.0 | 2026-07-26 | Epic 13 (F9 Otboy) | T-084–T-092 | 305 |
| v2.11.0 | 2026-07-28 | Epic 14 (Album Fix) | T-093–T-099 | 316 |
| v2.12.0 | 2026-07-28 | Epic 15 (Common Service) | T-100–T-107 | 372 |
| v2.12.1 | 2026-07-29 | Epic 16 (Bug Fixes) | T-109–T-115 | 387 |
| v2.13.0 | 2026-07-30 | Epic 17 (Danger Word Fix) | T2–T4 | 399 |
| v2.15.0 | 2026-08-02 | 4 Major Fixes | — | 458 |
| v2.16.0 | 2026-08-02 | Epic 18 (Danger Service Fixes) | A/B/C | 478 |
| v2.17.0 | 2026-08-02 | Epic 19 (Olya Service) | T-131–T-138 | 509 |
| v2.18.0 | 2026-08-02 | Epic 20 (Slavik Random Media) | T-139–T-148 | 570 |
| **v2.19.0** | **2026-08-03** | **Epic 21 (MIMIC fix + Time-format cooldowns)** | **T-149–T-162** | **586** |
| **v2.20.0** | **2026-08-15** | **Epic 22 (Гонка функций и точность триггеров)** | **T-163–T-167 (DEPLOYED, `1dbb6da`)** | **621** |
| **v2.21.0** | **2026-08-16** | **Epic 23 (Правка danger-словаря)** | **T-169–T-172 (DONE & DEPLOYED, `756d237`)** | **672** |

---

### Sprint Status

| Status | Tasks |
|--------|-------|
| **DEPLOYED** | T-001 – T-148 + T2/T3/T4 + v2.15.0 fixes + Epic 18 A/B/C (DEPLOYED across 20 Epics) ✅ |
| **DEPLOYED** | Epic 21: T-149 – T-162 (DEPLOYED, commit c683903, 586 tests pass) ✅ |
| **DEPLOYED** | Epic 22: T-163 – T-167 (DEPLOYED, commit `1dbb6da`, 621 tests pass, прод v2.20.0) ✅ |
| **DEPLOYED** | Chore T-168: danger_drone.mp4 в danger-пул — DONE & DEPLOYED ✅ (коммит `0c74220`, pull 1dbb6da..0c74220, chmod 644, хэш совпал, пул 16 файлов, PID 916795, smoke OK) |
| **DEPLOYED** | Epic 23: T-169 – T-172 (DONE & DEPLOYED ✅, коммит `756d237`, 672 теста, прод v2.21.0, PID 917681) — словарь 118 слов + 17 фраз, .env DANGER_WORDS пустой (дефолты активны), проверка «118 17» совпала, логи чистые |

> Epics 1-22 ALL DEPLOYED ✅ (v2.20.0, commit `1dbb6da`, PID 914116). **Epic 22 «Гонка функций и точность триггеров» DONE & DEPLOYED ✅ — реализация (D51–D54) + ревью 3 раунда (APPROVED) + коммит/пуш/деплой (T-167-D).**
> 621 тест. 11 роутеров, 5 таблиц БД, Sentry + Logtail мониторинг.
> MIMIC propagation FIXED. All 6 cooldowns in time-format (1s/1m/1h/1d).
> Epic 22 реализовано и задеплоено: D51 (Olya SaveAsBot-only, OLYA_ALWAYS_SEND=False), D52 (MIMIC_FORWARDS_ENABLED=False), D53 (Slavik race fix, DEAD_PAGE_POST_ON_JOIN=False), D54 (PostPicker last-sent). v2.20.0, 621 тест.

---

## 🚀 Deployment Details

| Параметр | Значение |
|----------|----------|
| **Версия в проде** | v2.21.0 (Epic 23 DEPLOYED) |
| **Текущий коммит** | `756d237` (feat(danger): Epic 23 — точная настройка danger-словаря (v2.21.0); прод HEAD после pull 0c74220..756d237) |
| **Дата** | 2026-08-16 |
| **Сервер** | 198.46.175.136 |
| **Путь** | /var/www/admin_bot |
| **Статус** | systemctl status adminbot → active (running), PID 917681, логи чистые (Bot started, listening...) |
| **Git remote** | origin (github.com/Henry-Case-dev/adminbot.git) — pushed успешно |
| **Тесты** | 672 PASS (621 baseline + 51 Epic 23) |
| **Эпики** | 1-23 ALL DEPLOYED ✅ |
| **Задачи** | T-001 – T-172 ALL DEPLOYED ✅ |
| **.env на проде** | DANGER_WORDS пустой → дефолты активны (118 слов + 17 фраз); DEAD_PAGE_POST_ON_JOIN=False; OLYA_ALWAYS_SEND и MIMIC_FORWARDS_ENABLED — дефолты False |
| **Ошибки** | 0 errors в production логах. Все сервисы инициализированы корректно. |

---

*Обновление: 2026-08-16 — ЗАФИКСИРОВАНА ПОЛИТИКА MEDIA-ПАПКИ (указание пользователя): всё, что добавляется/удаляется в media/ (media/common/danger, media/olya/cringe, media/slavik_random и т.п.), делается СОЗНАТЕЛЬНО и СПЕЦИАЛЬНО для загрузки на сервер и использования ботом; media-файлы НЕ исключаются из коммитов как мусор, НЕ добавляются в .gitignore, НЕ удаляются без явного указания. Рекомендация «danger_drone.mp4 → .gitignore» — ОШИБОЧНАЯ, ОТМЕНЕНА. danger_drone.mp4 — 16-й файл danger-пула, добавлен намеренно. Новая chore-задача: коммит + деплой media/common/danger/danger_drone.mp4.*

*Обновление: 2026-08-15 — EPIC 22 STATUS: DONE & DEPLOYED ✅ (v2.20.0, коммит `1dbb6da`). «Гонка функций и точность триггеров» — PM-решения D51–D54 реализованы и задеплоены (Olya SaveAsBot-only / MIMIC_FORWARDS_ENABLED=False / Slavik race fix / PostPicker last-sent). Задачи T-163–T-167 (A/B/C/D) выполнены: ревью 3 раунда APPROVED, 621 тест PASS (586 baseline + 35 новых), 0 регрессий. Деплой: сервер 198.46.175.136:/var/www/admin_bot, git pull c683903..1dbb6da (21 файл, +1778/-224), systemctl restart OK, active (running), PID 914116 (был 699945), логи чистые. Prod .env: DEAD_PAGE_POST_ON_JOIN=True→False (бэкап .env.bak.2026-08-15); OLYA_ALWAYS_SEND и MIMIC_FORWARDS_ENABLED отсутствуют — дефолты False. media/common/danger/danger_drone.mp4 — добавлен намеренно (16-й файл danger-пула), к коммиту и деплою; рекомендация про .gitignore ОТМЕНЕНА пользователем (2026-08-16).*

*Предыдущий статус (2026-08-15): EPIC 22 IMPLEMENTED + APPROVED ✅ (коммит и деплой pending). T-163–T-167-C выполнены @Builder, ревью 3 раунда — APPROVED. 621 тест PASS. НЕ закоммичен/НЕ задеплоен (базовый коммит c683903 v2.19.0 в проде).*

*Предыдущий статус (2026-08-03): EPIC 21 STATUS: DEPLOYED ✅. MIMIC propagation fix (D49: return UNHANDLED in alan_handler, 3 code paths). Time-format cooldowns (D50: _parse_duration с 1s/1m/1h/1d, 6 полей переименовано). 586 тестов пасс. All 14 tasks T-149–T-162 COMPLETE + DEPLOYED. Commit c683903, push origin/master.*

*Обновление: 2026-08-16 — CHORE T-168: IN PROGRESS 🚧. PM добавил T-168 в backlog.md (T-168-A..E + AC) и board.md (In Progress, @Builder): chore — коммит + деплой `media/common/danger/danger_drone.mp4` (16-й файл danger-пула). Architect добавил Section 31 в ARCHITECTURE.md (Конвенция media/ + инвентарь пулов). Код не требуется — media_picker подхватывает файл автоматически. Ожидает @Builder: verify → коммит `chore(media): danger_drone.mp4 в danger-пул` (на русском) → push → деплой (git pull на 198.46.175.136) → verify на сервере → smoke test. Соблюдать политику media/: НЕ в .gitignore, НЕ удалять.*

*Обновление: 2026-08-16 — CHORE T-168: A/B DONE ✅, APPROVED ревьюером. Коммит `0c74220` (chore(media): danger_drone.mp4 в danger-пул) сделан и запушен в master. Состав: 1 медиа-файл + 4 plans-файла, кода нет. danger_drone.mp4 закоммичен (blob `918c9be9…`, 2 574 925 байт, ftyp isom/MP4), working tree clean. C/D/E (деплой на сервер / verify на сервере / smoke test) — PENDING. Прод пока на `1dbb6da` (v2.20.0) до деплоя.*

*Обновление: 2026-08-16 — CHORE T-168: DONE & DEPLOYED ✅. Все подзадачи A..E закрыты. Деплой: git pull на сервере fast-forward 1dbb6da..0c74220 (5 файлов: danger_drone.mp4 + 4 plans). danger_drone.mp4 на месте (2 574 925 байт), права 644, хэш 918c9be9... совпал, danger-пул = 16 файлов. systemctl restart OK: active (running), PID 916795, логи чистые. Smoke test пройден. Прод HEAD = 0c74220 (v2.20.0 + медиа).*

*Обновление: 2026-08-16 — EPIC 23: IMPLEMENTED + APPROVED ✅ (коммит/деплой PENDING). «Правка danger-словаря» — T-169..T-171 DONE: DANGER_WORDS 191→118 (удалены Flight/Shelter/Атака-угроза/Падение-сбитие; добавлены хлопок/хлопки/хлопнуло/хлопнул), новая DANGER_PHRASES=17 (10 shelter + 7 атака, longest-first). Механика: _build_phrase_patterns в DangerWordFilter — фразы→слова, {"matched_word"} совместимо, env-независимо. Тесты: 672 PASS (621+51; TestDangerPhrases 42 кейса, контракт 17 фраз, негативы). Ревью 2 раунда APPROVED (2 фикса тестов выполнены дословно). T-172 (README/доки/коммит/деплой) PENDING. Прод на 0c74220 (v2.20.0 + T-168 media). Целевая версия v2.21.0.*

*Обновление: 2026-08-16 — EPIC 23: T-172-A..D DONE ✅, деплой (E..G) PENDING — DevOps. README: v2.21.0, 672 теста, «187 словоформ» → 118 слов + 17 фраз (135 паттернов), примеры словаря (атака/угроза/прилет → фразы, добавлен хлопок), changelog «Изменено в v2.21.0 (Epic 23)» с D55–D58. backlog: T-169..T-171 [x], T-172-A..D [x], деплой [ ]; статус Epic 23 → IMPLEMENTED (APPROVED, деплой pending). board: Epic 23 → In Review с пометкой «APPROVED, деплой pending», футер синхронизирован. Коммит feat(danger) на master + push в origin. Состав: word_lists.py, danger_word.py, test_filters.py, test_common.py, README.md, ARCHITECTURE.md, MEMORY.md, backlog.md, board.md. Прод на 0c74220 (v2.20.0 + T-168 media).*

*Обновление: 2026-08-16 — EPIC 23: IN PROGRESS 🚧 (СПЛАНИРОВАН, целевая версия v2.21.0). PM и Architect спланировали Epic 23 «Правка danger-словаря»: решения D55–D58, задачи T-169..T-172. DANGER_WORDS: 118 словоформ (было 191) — удалены секции Flight (10), Shelter (26), Атака/угроза (28), Падение/сбитие (13); добавлены хлопок/хлопки/хлопнуло/хлопнул. Новая DANGER_PHRASES (17 фраз: 10 shelter + 7 атака). Механика: _build_phrase_patterns в DangerWordFilter — фразы проверяются до слов, границы по краям фразы, IGNORECASE, возврат {"matched_word": ...} совместимый. Потребители: war_alert (4b) и danger_handler (4c) — единый словарь. Итог 135 паттернов; target ≈646 тестов. Прод .env не трогаем.*

*Обновление: 2026-08-16 — EPIC 23: DONE & DEPLOYED ✅ (v2.21.0, коммит `756d237`). Деплой: git pull 0c74220..756d237 (9 файлов) на 198.46.175.136:/var/www/admin_bot, systemctl restart OK — active (running) PID 917681, логи чистые. .env DANGER_WORDS пустой → активны дефолты word_lists.py (118 слов + 17 фраз, 135 паттернов). Python-проверка «118 17» на сервере совпала. Все 23 Epic'а COMPLETE и DEPLOYED. Прод v2.21.0, бот активен, 0 ошибок.*
