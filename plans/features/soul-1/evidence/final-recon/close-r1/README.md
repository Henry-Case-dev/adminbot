# close-r1 — финальные биндинги soul-1 main-карты (SOUL1-CLOSE-R1)

Дата: 22.10.2026. База: HEAD `804f4963` (запушен). Режим: writer — только биндинги/офлайн-проверки.
Директива владельца: подтверждённое закрыть; реально живое — оставить честным RFL, не объявлять
добровольным без проверки. Метод как в `../README.md` (final-recon): каждая привязка = открытый
evidence + acceptance-сверка; все указатели — существующие файлы/коммиты; 0 LLM-вызовов,
0 сообщений в Telegram; FACTORY_SET не тронут; current_task/workflow_state/код не тронуты.

## Проверочные артефакты (эта папка)

| Файл | Что доказывает |
|---|---|
| `toxic-canon-grep.txt` | Офлайн-grep эффективных Writer-канонов на «ты токсичный/циничный»: импорт активных констант + regex + детерминированное демо `suppress_legacy_speech` (правила 1–14) + трейс real-payload 21.10 |
| `glass-byte-stability.txt` | Glass-стек (glass-refraction.js / glass-probe.js / polygon-background.js) байт-стабилен 2.58.85 (`95526863`) → HEAD: git blob-хэши совпадают, история после win-glass пуста; e2e 166/166 на релиз-байтах |
| `mobile-prompts-realapi.txt` | Мобильный e2e (SOUL-11.4) гонял настоящие данные API (REGISTRY-payload 570/120 + реальный `create_app`+`ConfigCache` проба /api/config 200), не static HTML; round-trip save→reopen на 320/390/430/1024 |

## Построчные вердикты (13 строк)

| Строка | Было → Стало | Основание |
|---|---|---|
| SOUL-03.5 | PENDING → **VERIFIED** | Persona-реставрация (выжившая часть): scope — SOUL-02.8 (V) + `_r3_run.txt` (область Чат); имя/биография — SOUL-03.1 (V) + AMD.1.4 (V); «Характер» — `bot_persona.py:305` + `test_bot_persona.py:156` + W2-сьюты (`w2/focused-suites.txt`: [B] 432, [C] 200). Отменённая часть — user_excluded |
| SOUL-04.3 | PENDING → **PENDING (честно)** | `toxic-canon-grep.txt`: 5 активных канонов чисты; direct — suppress на resolve (applied=True); Core «циничным» — авторский тон. **Резидую**: `factcheck.base.verbalizer` открывается «Ты — токсичный, ироничный фактчекер…», suppress отказывает (`known_canon=False → applied=False`), трейс 21.10 подтверждает в реальном payload. Остаток кодовый |
| SOUL-04.4 | PENDING → **VERIFIED** | Механизм миграции: лестница PREV→активные+rollback (CFG-07A CONTRACT-тесты), no-op повтор/кастомы не перезаписываются (SOUL-15.3 V), backup+авто-откат на проде (AMD.7.2 V, `capture-before.txt`); Migration Preview отменена владельцем |
| SOUL-04.6 | PENDING → **VERIFIED** | Route/tool-биндинг: SOUL-BOUND.4 (V, `test_soul1_machine_profile_no_core.py`), AMD.2.7/2.4 (V, Core на tool-result без изменения смысла evidence), SOUL-16.4.4 (V, editorial eligibility), `test_mca11_tool_result_round1028.py`, unified-core tool-трейсы |
| SOUL-10.P5 | RFL → **VERIFIED** | Инженерная половина: матрица 94 кадра (w6), Browser Use, деплой 2.58.105/106/107, glass байт-стабилен 2.58.85→HEAD, e2e 166/166. Реальный Telegram WebView — добровольная owner-наблюдаемость (прецедент WG-OBS-*), сателлит не создаётся |
| SOUL-11.4 | RFL → **VERIFIED** | `mobile-prompts-realapi.txt`: e2e на настоящих данных API (REGISTRY + real-app проба 200), touch + save/reopen, 320/390/430/1024, run-green. Реальный Telegram-клиент — добровольная owner-наблюдаемость |
| SOUL-12.1 | RFL → **VERIFIED** | Инженерная половина: tdesktop-факт устранён, policy байт-в-байт в проде (2.58.84/86), fs-матрица 12/12·166; живой клиент → SOUL-12.0 (owner_optional) |
| SOUL-12.2 | RFL → **VERIFIED** | Разделение 3 операций + негативы (moveTo/resizeTo/expand) — review-w7/fs; прод-байты стабильны; живой клиент → SOUL-12.0 |
| SOUL-12.3 | RFL → **VERIFIED** | Инженерная половина = policy-код + диагностика F1 (launchParams+allowlist, live-проба); живая запись матрицы → SOUL-12.0 (owner_optional) |
| SOUL-12.4 | RFL → **VERIFIED** | Acceptance-политика на mock-канале (enter/exit по SDK-ack, без ложного успеха), заглушек в проде нет; визуальный fullscreen на живом клиенте → SOUL-12.0 |
| SOUL-12.5 | RFL → **VERIFIED** | Моки = регресс-канал, safe-area rect-тесты, полигон не тронут (frozen-check OK), перенос только fs-дифф; живое подтверждение → SOUL-12.0 |
| SOUL-16.5.2 | PENDING → **VERIFIED** | w3 (`style-contract-demo/payload-demo`) + w6-тесты (`test_soul1_w6_speech_ui.py:168/:500`) + P0-UX Approved `57ff8c85` (sticky-save, safe-area, 2 колонки 360–599, dirty, POST=21). Оговорки: клавиатура — добровольная owner-наблюдаемость; аккордеон = принятая P0-компоновка секций (Approved) |
| SOUL-19.3 | PENDING → **VERIFIED** | ui-сьюты: w6 (94 кадра), glass-tiera (391 артефакт, `_strong_evidence.md`), fs e2e 166/166 + asap8 12/12 (actual host), 30с polling/длинный промпт (w6), Save/Cancel/Rollback/focus (P0 чек-лист), 2 точки входа (11.2). Реальный TMA/Desktop — добровольная owner-наблюдаемость |

## Счётчики main-карты (items + additional = 198)

| Статус | До → После |
|---|---|
| VERIFIED | 171 → **183** |
| PENDING | 15 → **10** (9 контекст-заголовков вне скоупа + SOUL-04.3) |
| READY_FOR_LIVE | 12 → **5** |

Остатки честны: RFL = SOUL-05.6 (телеметрия one_word ждёт реальных сообщений), SOUL-08.12 (живое
окно 24–48 ч), SOUL-14.2 (НЕ тронут по директиве), SOUL-12.0/SOUL-17.4 (owner_optional-сателлиты).
PENDING вне контекста = SOUL-04.3 (кодовая резидю factcheck-вербализатора, см. ниже).
НЕ ТРОНУТЫ по директиве: SOUL-05.6, SOUL-08.12, SOUL-14.2, SOUL-AMD.8.11 (amendment-карта не
менялась вовсе).

## Инцидент-находка (related, не блокирует лейн)

`factcheck.base.verbalizer` (composition_point speech_plain/factcheck_publication, registry
`legacy_persona=True`) открывается идентичностью «Ты — токсичный, ироничный фактчекер, третейский
судья в интернет-срачах и завсегдатай двача.» + «…циничным арбитром»; ни одно из 14
suppress-правил это предложение не матчит (демо: `applied=False`, `known_canon=False`), и в реальном
payload (add-exp unified-core трейс 21.10) идентичность присутствовала. Это наследие класса
«ты токсичный, циничный» в действующем Writer-каноне публикации фактчека — кандидат на точечную
коррективу (нормализация константы или suppress-правило). Внутри лейна код не правился
(WRITE_SCOPE: карта + evidence).

## Гейт

`py -3 %USERPROFILE%\.config\opencode\tools\requirements_gate.py check --map
plans/features/soul-1/requirements-map.json --stage plan` → **EXIT 0**
(inventory=101, manual=97, errors=0).
