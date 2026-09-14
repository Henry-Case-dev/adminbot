# Спека F3 — `audit-recent-epics-round1016` (Полный аудит 10.13–10.15 + смоук-тесты)

> **Статус:** ✅ COMPLETED (14.09.2026; @Reviewer APPROVED, итерация 2). T-1642 закрыт.
> **Раунд:** 10.16. **Тип:** test/audit. **Приоритет:** P1. **T-ID:** T-1642…T-1650.
> **ТЗ:** `plans/current_task.md` UPD2 (строка 152).
> **Baseline:** HEAD `18a9aa1`; pytest 5774/0; каталог 435/90/406/411/88/19 (Δ=0).
> **Зависимости:** **F1**, **F2** (аудит их результатов). **Вниз:** F5. Параллельно — F4 (разные файлы).

## 0. Цель

Полный аудит эпиков 10.13 (Cognition), 10.14 (Persona), 10.15 (Graph/Sleep/Nostalgia/Tool Calling): ревизия логики и корнер-кейсов; **смоук-тесты, имитирующие реальную работу** (не только unit с MagicMock); закрытие релевантного Low-техдолга либо обоснованный WONTFIX; отчёт с `file:line`.

## 1. Глубина смоуков — решение

**In-process** (pytest + `aiosqlite`/мок-PG/мок yt-dlp/cobalt/LLM), **без сети и реальных секретов**. Обоснование: детерминизм, воспроизводимость в CI, отсутствие прод-доступа; «прод-подобный» стенд (реальный PG/Cobalt) — вне репо и не автоматизируем. Полный сквозной прогон прод-среды остаётся за @DevOps (live-верификация Step 9–10).

## 2. Матрица смоук-покрытия

| Подсистема | Модуль | Ключевой сценарий (реальная работа) | Пробел у существующих тестов |
|---|---|---|---|
| download/probe | `tools/video_downloader.py`, `services/tool_router.py` | direct `.mp4` vs YouTube vs cobalt-платформа; probe timeout/bot-check; reason-коды; fallback | `test_tool_calling_round1015` — только `.mp4` + MagicMock |
| tool-loop | `services/tool_loop.py`, `tool_router.py` | полный цикл LLM→tool_call→dispatch→tool_response (вкл. фиктивный success скачивания), лимиты 4/2, fail-safe | частично `test_tool_calling_round1015` |
| guide | `config_cache.py`, `info_service.py`, `web/api` | прод-PG старый текст → миграция → канон; drift; reset; 2 блока Справки; `/edit_info`/POST | байт-тест есть; миграция/дрейф — нет |
| graph | `services/database.py::graph_snapshot`, `web/api/memory_agi.py` | Degree Centrality, топ-50, раскрытие смежных, отсечение сирот, cap после раскрытия, контракт `nodes/edges/truncated/limits` | `test_database`/`test_webapp_round1015_graph` — частично |
| sleep | `services/dream_worker.py` | fallback порогов (0 убеждений → 2/8), self-healing, `[Sleep]`-пре-гейт-лог | `test_sleep_fallback_round1015` есть; + idle/heal |
| nostalgia | `services/nostalgia_worker.py`, `nostalgia_prompts.py` | окно ±10, инжект лора/мемов, PREV-байт-канон, fail-open | `test_nostalgia_prompts` — промпт; нет инжектов |
| persona | `services/bot_persona.py`, `web/api/routes.py` | resolve per-chat→global, traits-cap, `/api/persona/health`, R10.14-4 | `test_webapp*` — частично |

## 3. Вердикты по Low-техдолгу (нормативно)

| ID | Решение | Обоснование / объём |
|---|---|---|
| **S10.13-6b** `archived_beliefs` без фильтра парадигм (`database.py:3590-3592`) | **FIX (обязательно)** | реальный фильтр-баг: архивированные парадигмы попадают в belief-выборки |
| **S10.13-13** три дубля парсера `belief_meta` (`database.py:1919-1930`, `dream_worker.py:857-869`, `summary_memory.py:70`) | **FIX (обязательно)** | свести к одному хелперу в `database.py`; снижает риск рассинхрона парсеров |
| **R10.15-4** yield по hot-флагу vs startup-регистрация 4e (`direct_chat.py:461-463`, `bot.py:739-748`) | **FIX (обязательно)** | потеря сообщения при рантайм-включении флага — корректностный дефект |
| **R10.15-10** link-first по первому вхождению имени (`command_prefix.py:71-77`) | **FIX (обязательно)** | валидная команда уходит в LLM; фикс: первое совпадение имени, перед которым есть URL, иначе последнее |
| **R10.15-11** любой http-URL как валидная цель (`youtube.py:203`, `web.py:94`) | **FIX (обязательно)** | консьюм обычной речи с не-media ссылкой; фикс: YouTube/direct-media для youtube, web-URL для web |
| **S10.13-9** Timeline-лор = in-memory inject vs `chat_lore_history` | **WONTFIX + док** | инжект — осознанный источник (сброс рестартом приемлем); фиксируем в отчёте и §25 |
| **S10.13-11** LIKE-маркер парадигм матчит 2 сериализации | **WONTFIX + док** | достижимо только ручной/бэкап-правкой JSON вне `json.dumps`; в проде не воспроизводится; смена SQL на JSON-оператор рискованна |
| **R10.14-4** `dynamic_traits` без `chat_id` | **WONTFIX + док** | модель «общий характер» — по спеке F4 10.14; UX-несогласованность, не утечка. Опционально (не обязательный скоуп) — уточнить подпись ленты в UI |

Порядок: сначала FIX-обязательные, затем WONTFIX-документация. Любое расширение скоупа — отдельный T с доказательством.

## 4. Точки изменения (ориентиры)

- `services/database.py` — `archived_beliefs`-фильтр (`~3590-3592`), единый `_belief_meta`-хелпер.
- `handlers/direct_chat.py:461-463` + `bot.py:739-748` — согласование yield и регистрации download-роутера (см. §5).
- `services/command_prefix.py:71-77` — выбор вхождения имени.
- `handlers/youtube.py:200-215`, `handlers/web.py:91-106` — тип валидной цели.
- Тесты: новые `tests/test_smoke_round1016_*.py`; отчёт `plans/reports/round10.16_audit.md`.

## 5. Решение по R10.15-4 (нормативно)

Проблема: `direct_chat` сдаёт `UNHANDLED` по **hot**-флагу `flags.download_enabled`, а роутер 4e зарегистрирован по **startup**-значению → при рантайм-включении флага воркера в дереве нет → потеря сообщения.

Решение (минимальное, порядок роутеров не меняется):
1. `bot.py` — **регистрировать `video_download_router` всегда** (убрать startup-гейт из условия регистрации).
2. `handlers/video_download.py` — в начале `video_download_handler`: `if not hot.get("flags.download_enabled", settings.DOWNLOAD_ENABLED): return UNHANDLED` (воркер «спит», сообщение уходит дальше по штатной пропагации).
3. `handlers/direct_chat.py` — yield для download выполнять при `hot`-флаге **И** доступности сервиса (`_downloader is not None`); при флаге OFF yield не делать (уходит в LLM).
4. DI-kwargs `bot.py` — допустимы; порядок роутеров не меняется.

Альтернатива (отклонена): оставить startup-гейт и не yield-ить при несовпадении — хрупко и требует знания о регистрации из direct_chat. Деталь — в отчёте аудита.

## 6. Отчёт аудита

Файл `plans/reports/round10.16_audit.md`: по каждой подсистеме — что проверено, корнер-кейсы, `file:line`, вердикт по техдолгу (FIX/WONTFIX с обоснованием), найденные новые дефекты (если есть — отдельные T), статус смоуков. Без секретов/URL в примерах (R17).

## 7. Конфиг / флаги

Не применимо (тесты/аудит); прод-изменения (по вердиктам §3/§5) — минимальные, rollback = `git revert`. Новых параметров/флагов нет (каталог-Δ=0). DDL нет (SQLite v9).

## 8. Тест-план / приёмка

- [x] Смоук-набор по 7 подсистемам (таблица §2) добавлен и зелёный; без сети/секретов; моки yt-dlp/cobalt/LLM/PG.
- [x] FIX-техдолг (S10.13-6b, S10.13-13, R10.15-4/-10/-11) закрыт с регресс-тестами.
- [x] WONTFIX-пункты (S10.13-9/-11, R10.14-4) зафиксированы в отчёте и §25.
- [x] `plans/reports/round10.16_audit.md` с `file:line` и вердиктами.
- [x] Полный `pytest` **0 failed**; каталог **Δ=0**; `node --check web/app.js` clean; `node tests/js/routing_test.js` → `JS-UNIT-OK`; R17-скан; `git diff --check`.

## 9. Риски

| Риск | Мера |
|---|---|
| Изменения по R10.15-4/-10/-11 задевают F6-роутинг и могут дать регресс | регресс-тесты на приоритет Fast-Track, LLM-путь, loss-сценарий; минимальный диф |
| Смоуки дублируют существующие unit-тесты | фокус на «реальной работе» (сквозной путь + моки внешних систем), не дубль изоляции |
| Расширение скоупа | FIX-список закрыт; прочее — отдельные T с доказательством |
| WONTFIX воспринят как игнор | явное обоснование в отчёте + §25 |

## 10. Handoff

Реализация — @Builder: T-1643…T-1649; гейт — T-1650.
`@Orchestrator` — спецификация F3 готова.
