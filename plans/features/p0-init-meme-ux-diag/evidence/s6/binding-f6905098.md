# S6-FRESH — доказательная привязка к кандидату `f6905098`

Эпик: `p0-init-meme-ux-diag` · срез **S6-FRESH** («Effective-состояние, время и
разграничение чатов»). Строки контракта: `P0IM-S6-EFFECTIVE`, `P0IM-S6-TZ`,
`P0IM-S6-SCOPE`, `P0IM-S6-EXPIRED`.

## 0. База и границы

* **База: `83eb0b9b`** (ветка `init/meme-s5b`, вершина одобренного S5b + его
  доказательные коммиты). Рабочая ветка: `init/meme-s6`.
  Причина: мастер-ветка отстаёт от продажи (в ней `web/app.js` ≈ 1 006
  строк диагностики против 2 823 на этой базе), а S6 продолжает работать по
  уже сданному read-model осей (S1-AXES/S3-OV/S4-TRACE).
* **База ≠ продакшн.** Продакшн на момент среза — `7a7cd0ce` (2.58.193).
  Паритет с развёрнутым кодом здесь НЕ заявляется: скриншоты показывают
  поведение кандидата на базе `83eb0b9b`, а не поведение продажи.
  Сравнение с живой продажей — работа релизного шага.
* Новых эндпоинтов, таблиц, флагов, промптов, моделей и настроек нет. Всё
  аддитивно к существующему `collect_mechanism_diagnostics` и существующим
  экранам инициативы.

## 1. EFFECTIVE (`P0IM-S6-EFFECTIVE`)

**Ответ.** Решает не одна строка, а упорядоченный набор гейтов; каждый гейт
называет СВОЙ слой. Поле `configuration.layers` (`CONFIGURATION_LAYER_FIELDS`)
отдаёт по одному элементу на гейт:

```
{"gate": "module_gate|observer|chat_toggle|meme_settings|image_module",
 "layer": "chat|global|factory|env|read_failed",
 "enabled": true|false|null, "source": ..., "reason": ...}
```

Источник слоя (`services/initiative_diagnostics.py`):

| гейт | откуда слой | файл:строка |
|---|---|---|
| `module_gate` | `module_registry.effective_gate("initiative")`: `emergency_env` → `env`, иначе `global` | `_gate_parts` |
| `observer` | мастер-флаг наблюдателя → `global` | `_gate_parts` |
| `chat_toggle` | `observer.chat_capability_state().source`: `chat` → `chat`, **`default` → `factory`**, иначе `global` | `_gate_parts` |
| `meme_settings` | `chat_params.get_chat_param_sourced(chat, meme.KEY_ENABLED, DEFAULT_ENABLED)` → `chat|global|factory` | `_meme_settings_layer` |
| `image_module` | выключенный модуль картинок → `global` | `_meme_configuration_parts` |

Исправленные дефекты принадлежности:
1. **Заводское значение выдавалось за «общую настройку»**: `chat_toggle`
   сообщал `source="global"`/`scope="global"` при `CapabilityState.source ==
   "default"`. Теперь `layer="factory"`.
2. **Настройка мемов всегда называлась «настройки этого чата»** —
   `scope="chat"` ставился безусловно, даже когда значение пришло из
   заводского дефолта модуля (`DEFAULT_ENABLED = False`). Теперь слой берётся
   из того же резолвера, что читает боевой `load_settings`.
3. **Сбой чтения настройки** (`get_chat_param_sourced` бросил) больше не
   выдаётся за `false`/`disabled_by_setting`: гейт получает `enabled=null`,
   `layer=read_failed`, и ось целиком становится `enabled=null`
   (`source=read_failed`) — «неизвестно», а не правдоподобный дефолт.
   Агрегат `enabled/source/scope/reason` не переписан: сохранена прежняя
   интерпретация статуса.

**Было → стало (витрина, карточка):**
```
было:   Разрешено: включено — настройка этого чата
стало:  Разрешено: включено — настройка этого чата
        Слои решения: модуль инициативы — общий слой; наблюдатель — общий
        слой; тумблер этого чата — слой чата; настройки мемов — заводское
        значение
```
Запрещающий или нечитаемый гейт печатается словами:
`<гейт>: запрещает · <слой>` / `<гейт>: неизвестно · <слой>`.

**Доказательства:** `tests/test_p0im_s6_fresh.py::test_configuration_layers_name_the_real_layer`
(три прогона на одной БД, отличается только слой резолвера),
`::test_unreadable_config_is_unknown_not_a_default`,
`::test_unreadable_chat_gate_is_unknown_not_global`;
`tests/js/initiative_ui_rework_test.js` (`s6FreshSuite`, подпись слоёв и
отсутствие подписи без данных);
`tests/ui_initiative_rework_e2e.py` (`run_s6_scope`, оба вида 1536×960 и
390×844).

## 2. TIME (`P0IM-S6-TZ`)

**Ответ.** Пояс приходит из backend одним объектом в каждом ответе
диагностики:

```
"time": {"generated_at": <int>, "basis": "server_snapshot",
         "timezone": {"name": "Europe/Moscow"|null,
                      "source": "chat|global|utc_fallback|read_failed",
                      "offset_seconds": 10800|null,
                      "default_name": "UTC", "reason": ""}}
```

* `name/source` — из существующего `meme_initiative.resolve_timezone(chat_id)`
  (тот же резолвер, что у боевого `day_window`; второй интерпретации нет).
* `offset_seconds` считается на момент снимка через `ZoneInfo`, поэтому
  лето/зима различаются (`Europe/Berlin`: 3600 зимой, 7200 летом).
* **Пояс чата не задан** ни на одном слое → `source="utc_fallback"`,
  `name="UTC"`, `default_name="UTC"`: это НАЗВАННЫЙ заводской пояс, а не часы
  сервера. Витрина печатает «пояс чата не задан — UTC (заводское значение, не
  часы сервера)».
* **Сбой чтения** слоя настроек (`resolve_timezone(..., strict=True)`)
  пробрасывается: `name=null`, `source="read_failed"`,
  `reason="timezone_read_failed"`, `offset_seconds=null`. Витрина печатает
  «пояс чата не прочитан — время в UTC» и помечает время суффиксом `UTC`,
  а не выдаёт его за пояс чата. Боевой путь (`day_window`) остаётся
  fail-open: `strict` по умолчанию `False`.
* Клиент больше **не собирает пояс из `configItems`**: удалена
  `iniChatTimezone` и её два вызова. `computed.iniOverviewTimezone`/
  `iniOverviewTz` читают `iniTzOf(payload)` и отказываются подписывать время
  поясом чужого ответа (сверяется `payload.chat_id`).
* Пояс второго чата в режиме «другой чат» берётся из ЕГО ответа: время
  второго чата больше не подменяется UTC.
* Время списка событий обзора и «последнего решения» тоже переведено в пояс
  чата (`iniWhenFull`, с годом) — до правки они печатались локальным временем
  устройства.

**Было → стало (шапка обзора, чат A с override `Europe/Moscow`):**
```
было:   пояс чата: Europe/Moscow            (из глобального списка параметров)
стало:  пояс чата: Europe/Moscow (настройка чата)   (source=chat из ответа)
```
```
было (пояс не задан):  пояс чата не задан — время в UTC
стало:                 пояс чата не задан — UTC (заводское значение, не часы сервера)
```
```
было (события обзора): 15.01.2027, 20:05:00        (локальное время машины)
стало:                 15.01.2027, 11:05           (пояс чата, тот же момент, что в карточке)
```
```
было (другой чат):    время в UTC (пояс другого чата здесь не читается)
стало:                Время: пояс чата не задан — взят общий: Asia/Tokyo
```

**Доказательства:** `::test_time_block_names_chat_timezone_and_its_layer`,
`::test_missing_chat_timezone_falls_back_to_named_default`,
`::test_unreadable_timezone_is_unknown_not_utc`,
`::test_timezone_offset_follows_the_instant`;
JS: `s6FreshSuite` (пояс из payload, а не из `configItems`; разный пояс —
разная строка; без пояса — `UTC`; сбой → «не прочитан»);
e2e `run_s6_scope` (шапка + подпись пояса в карточке чужого чата).

## 3. SCOPE (`P0IM-S6-SCOPE`)

**Ответ.** `payload.chat_id` равен запрошенному `X-Chat-Id`; `time` описывает
тот же чат. Клиент фиксирует `{epoch, chatId}` до `await` и применяет ответ
только при совпадении `scopeEpoch` и `payload.chat_id` (существующий
`_chatBound`/`_payloadChatMatches`); поздний ответ другого чата НЕ
применяется и объясняется на экране; молчаливый выход при `memeDiagBusy`
устранён ранее (один in-flight + один хвост). Штамп свежести — серверный
`time.generated_at` того же ответа; подпись «снимок: … (сервер)».

Правки этого среза по SCOPE:
1. `iniManualPriorityActive` больше не сравнивает дедлайн с часами браузера:
   без серверного `checked_at` состояние не объявляется живым.
2. `iniOverviewTimezone`/`iniOverviewScope` не используют пояс чужого
   снимка (сверка `chat_id`), поэтому шапка не подписывается чужим ответом.
3. Вкладка «Публикации» догружает тот же снимок диагностики, если его нет, —
   чтобы одна и та же секунда на «Обзоре» и в журнале печаталась одинаково.

**Было → стало:**
```
было:  снимок: 15.01 11:05
стало: снимок: 15.01 11:05 (сервер)
```
```
было:  (нет подписи базиса и слоя пояса в разметке)
стало: data-ini-snapshot-basis="штамп снимка — сервер",
       data-ini-tz-source / data-ini-tz-name / data-ini-tz-known
```

**Доказательства:** `::test_payload_is_scoped_to_the_requested_chat`,
`::test_stale_response_for_another_chat_is_not_applicable`;
JS `s6FreshSuite` (поздний ответ другого чата → снимок не применён, причина
названа; штамп берётся из `time.generated_at`, а не из тела ответа и не из
часов клиента); e2e `run_overview` (`foreign_chat` — карточки не показывают
чужие числа, шапка не подписана).

## 4. EXPIRED (`P0IM-S6-EXPIRED`)

Истёкший маркер ручного `/meme` и просроченная бронь не обозначают текущее
ожидание: `publication.manual_priority_active=false`,
`manual_priority_expired=true`, просроченный `expires_at` не даёт
`readiness.state="busy"`, `next_basis` не ссылается на истёкший маркер.
Клиент не пересчитывает «жив ли приоритет» по своим часам.
Доказательство: `::test_expired_marker_and_claim_are_not_actual_waiting`,
JS `s6FreshSuite` (полоса координации не «отложено» без серверного штампа).

## 5. Мутации (проверка, что тесты кусают)

| № | Мутация | Ожидание | Наблюдено |
|---|---|---|---|
| 1 | `meme_initiative.resolve_timezone`: `if strict: raise` → `if False: raise` (сбой чтения снова схлопывается в UTC) | падает тест «сбой пояса = неизвестно» | `FAILED tests/test_p0im_s6_fresh.py::test_unreadable_timezone_is_unknown_not_utc`, остальные 9 прошли |
| 2 | `iniConfigLayersText` → `if (true) return ''` | падает JS-проверка слоёв | `AssertionError: заводский слой не назван: ` (s6FreshSuite) |

Обе мутации восстановлены; файлы возвращены к кандидату (сверено `git diff`).

## 6. Прогоны (кандидат `f6905098`, база `83eb0b9b`)

* `pytest tests/test_p0im_s6_fresh.py` — **10 passed**.
* `pytest tests/test_meme_init_diagnostics.py` — **43 passed**.
* `pytest tests/test_initiative_delivery_telemetry.py tests/test_meme_pipeline_api.py
  tests/test_evol014_meme_initiative.py tests/test_meme_init_diagnostics.py
  tests/test_p0im_s6_fresh.py tests/test_publication_binding_delivery.py
  tests/test_p0im_s5_meme_marker_interrupt.py` — **150 passed**.
* `node tests/js/initiative_ui_rework_test.js` — `INITIATIVE-UI-OK`.
* `python tests/ui_initiative_rework_e2e.py` (порт 8873, сервер поднят и снят
  самим стендом) — **failures=2**, оба ПРЕДСУЩЕСТВУЮТ на базе (см. §8).
  Все S6-проверки прошли на 1536×960 и 390×844.
* Полный прогон `tests/js/*.js`: 8 файлов падают, все 8 падают и на базе
  `83eb0b9b` без моих правок (проверено отдельным чистым worktree базы).

## 7. Линия и совместимость с продакшн-правкой честности

Продакшн `7a7cd0ce` содержит правки честности `f8846e49` и `a5d89cac` в тех
же двух файлах. Пересадка моих коммитов на `7a7cd0ce`:

* `web/app.js`: правка честности — один участок `@@ -22903,17 +22903,57 @@`
  (`moduleLastEventState` / `initiativeLastActionFact`). Мои участки —
  `4373…15617`, текстового пересечения нет.
  **Зависимость (важно):** `initiativeLastActionFact` вызывает
  `this.iniOverviewTimezone` и `iniWhen(at, tz)`; после пересадки строка
  «Последнее действие» будет печатать время в поясе из ОТВЕТА сервера, а не
  из списка глобальных параметров. Тест честности
  `tests/js/p0im_ov_honesty_test.js` подставляет `iniOverviewTimezone: ''`
  явно, поэтому остаётся валидным и после пересадки (проверено чтением
  `7a7cd0ce:tests/js/p0im_ov_honesty_test.js`).
* `web/index.html`: правка честности — участки около старых строк 1032-1043 и
  1881-1890 (`data-module-overview-actions`, ложная ветка «Последних действий
  в журнале нет»). Мой ближайший участок — `@@ -1896,8 +1896,12 @@` (строка
  пояса и штампа). Изменённые строки не совпадают, но участки соседние
  (зазор ≈ 5 строк): пересадку нужно применять и ПРОВЕРЯТЬ, а не полагаться
  на «чистый» merge — именно здесь возможно молчаливое выпадение правки
  честности.
* Удалённая мной `iniChatTimezone` на продакшне используется ровно в двух
  местах (`7a7cd0ce:web/app.js:10033,10041`), и оба места я переписываю —
  конфликт ожидаемый и локальный. Тестов, ссылающихся на
  `iniChatTimezone`, на продакшн-линии нет.

## 8. Что не проверено / ограничения

* **Паритет с продакшн-сборкой не заявлен.** Скриншоты — кандидат на базе
  `83eb0b9b`; живая продажа `7a7cd0ce` содержит правку честности, которой в
  этой базе нет. Сравнение с развёрнутым поведением — релизный шаг.
* **Живой production-снимок двух чатов** с реальным `X-Chat-Id` в этом срезе
  не снимался: `live_required/live_when=preprod` для строк S6 — проверка
  остаётся за релизом (read-only).
* **Browser Use** как отдельный рендер-контроль не применялся: стенд e2e
  отдаёт данные только через route-заглушки Playwright, поэтому обычный
  браузер увидит страницу без данных. Визуальная проверка выполнена по
  реальным рендерам Chromium (Playwright, 6 снимков в этом каталоге),
  просмотренным построчно.
* Pre-existing (не этот кандидат): 2 падения e2e `run_memes`
  («Исходный из кода · журнал недоступен») и 8 падающих `tests/js/*.js`,
  плюс 4 падения `tests/test_initiative_coordination.py` — воспроизведены на
  чистой базе `83eb0b9b` и на master-линии; вынесены наблюдателям как
  `BACKLOG_ONLY`.
* Сырой ISO `сброс: 2026-11-01T00:00:00+03:00` в карточке квоты мемов —
  прежнее поведение вкладки «Мемы» (смещение в строке названо), срезом не
  менялось.

## 9. Артефакты

| файл | что доказывает |
|---|---|
| `s6_self_1536.png` | шапка: пояс + слой пояса + «снимок … (сервер)»; строка «Слои решения» в двух карточках; события в поясе чата |
| `s6_self_390.png` | то же на 390×844 без обрезки и горизонтальной прокрутки |
| `s6_other_1536.png` / `s6_other_390.png` | карточка чужого чата: «Время: пояс чата не задан — взят общий: Asia/Tokyo» |
| `s6_tz_missing_1536.png` / `s6_tz_missing_390.png` | «пояс чата не задан — UTC (заводское значение, не часы сервера)» |
| `e2e-s6.json` | заметки прогона: поля `*-s6-self`, `*-s6-other`, `*-s6-tz-missing` и список failures |
