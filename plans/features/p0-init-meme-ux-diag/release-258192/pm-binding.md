# 2.58.192 — бухгалтерская привязка (PM)

Дата: 2026-11-12. Выложено: **2.58.192 = `bcc090a358d81d510f473b0bba1647a1979113a2`**
(`release/2.58.192`, рестарт `2026-11-11T19:05:11Z`), база `a6884ad7` (2.58.191), схема v47,
DDL=0, новых флагов/настроек нет, откат `a6884ad7`, снимок `/tmp/predeploy-258192.db`.
Дельта `a6884ad7..bcc090a3` — 52 файла, +5146/−116.

Это запись о **привязке доказательств и честной бухгалтерии**, не релиз, не правка кода и не
изменение общего `progress_scope.json` (его ведёт Orchestrator).

## 1. Что привязано в этом проходе

| Срез | Строк | Итог | Артефакт |
|---|---|---|---|
| S4-TRACE | 14 (11 уникальных) | 6 строк (4 уникальных) → **VERIFIED на `bcc090a3`**; 8 строк (7 уникальных) оставлены `PENDING` с названным недобором | `evidence/s4trace/binding-258192.md` |
| S1-AXES / `P0IM-BAN-NOETA` | 4 (один контракт, четыре исходных указателя) | **VERIFIED на `bcc090a3`** | `evidence/s1axes/binding-258192.md` |
| S1-AXES / `P0IM-BAN-CONFLATE` | 3 | `PENDING`, недобор уточнён (нет величины «сгенерировано») | `evidence/s1axes/binding-258192.md` |
| S3-OV / две живые несогласованности | 2 строки (`P0IM-OV-LIST`, `P0IM-OV-L3`) | остаются `REVIEW`, причины заменены на подтверждённые (LF-258192-01/02) | `live_findings` в карте |

Итого: **10 строк переведено в VERIFIED, 8 оставлено открытыми, 2 оставлены в REVIEW.**
Ни одна строка не повышена «за зелёную серию»: каждая VERIFIED опирается либо на живой
прод-проход по отданной сборке, либо (там, где живой носитель невозможен) на одобренные
тесты байт-идентичной сборки — и это прямо записано в привязке.

**Старые якоря не переписаны.** 44 ранее подтверждённые строки держат доказательства на
преддеплойных кандидатах (`4c59a483`, `726736ee`, `a6884ad7`, `c087253d`). Это не потеря:
их вердикты действительны для тех кандидатов, а перенос на `bcc090a3` требует отдельного
решения (перепривязка по побайтовой идентичности тел патчей или повторный прогон).

## 2. Итоги эпика после привязки

Всего в карте: **112 required-строк, 75 уникальных `req_id`** (несколько исходных указателей
одного обязательства делят один `req_id`).

| Статус | Строк | Уникальных |
|---|---|---|
| VERIFIED | 54 | — |
| REVIEW | 11 | — |
| PENDING | 47 | — |
| FAILED / READY_FOR_LIVE / BUILDING / Human Gate | 0 | — |

По срезам (строки / из них VERIFIED / REVIEW / PENDING):

| Срез | Строк | VERIFIED | REVIEW | PENDING |
|---|---|---|---|---|
| R0-INV | 9 | 9 | — | — |
| S1-AXES | 24 | 21 | — | 3 |
| S2-ID | 11 | 8 | — | 3 |
| S3-OV | 21 | 10 | 11 | — |
| S4-TRACE | 14 | 6 | — | 8 |
| S5-MEME | 6 | — | — | 6 |
| S5b | 3 | — | — | 3 |
| S6-FRESH | 6 | — | — | 6 |
| S7-ACCEPT | 17 | — | — | 17 |
| A0-ARCH | 1 | — | — | 1 |

**Полностью открытые срезы (ни одной VERIFIED-строки):** `S5-MEME` (6), `S5b` (3),
`S6-FRESH` (6), `S7-ACCEPT` (17), `A0-ARCH` (1).

Открытые внутри начатых срезов: `S4-TRACE` — 8 строк (`PB-LLM`, `PB-STEP`, `PB-FILTERS`,
`PB-MANUAL`, `PB-ACCESS`, `PB-COUNT`, `PB-VOCAB`), `S1-AXES` — `P0IM-BAN-CONFLATE` (3),
`S2-ID` — `P0IM-ID-FINISH` (2, остаточное окно `RW-D4-BOTH-WRITE-FAIL`) и `P0IM-ID-CONC`,
`S3-OV` — 11 строк `REVIEW`.

## 3. Почему `A0-ARCH` числится открытым

`P0IM-A0-CONTRACT` — дизайн-контракт: `architecture.md` существует и `DESIGN READY`,
но строка не имеет candidate-bound записи доказательства, поэтому остаётся `PENDING`.
Это бухгалтерский разрыв, а не открытый контрактный вопрос; в этом проходе строка
намеренно не трогалась (привязка S4/NOETA не даёт ей доказательства).

## 4. Две живые несогласованности 2.58.192 — как записаны

Обе записаны в карте в `live_findings`; задач из них не создавалось (`task_created: false`).

**LF-258192-01 — «время последней попытки» — `FIELD_MAPPING_UNDER_VERIFICATION`.**
Это не дефект часового пояса и не подтверждённый дефект продукта. Точные значения:

| Источник | Значение |
|---|---|
| `text_initiative.last_attempt.at` | `1794414460` = **2026-11-11T16:27:40Z**, `stop_stage=lease_held`, `run_id=init:-1004482340693:20261111:9926b6d84a` |
| `meme.last_attempt.at` | `1794414496` = **2026-11-11T16:28:16Z** |
| `text_initiative.readiness.next_eligible_at` | **2026-11-11T16:41:54Z** |
| БД `meme_initiative_attempt` 16:42:00–16:42:59Z | 14 строк = 7 попыток, `daily_quota_reached` |
| БД `mca_events` / `mca_bot_outputs` 16:42Z | 4 / 0 |
| БД по текстовой попытке `init:…9926b6d84a` | 0 строк |

Разница 14 м 14 с не кратна смещению зоны и оба значения пришли одним ответом API: 16:42 —
попытка мемов (или расчётная граница текста `16:41:54Z`), 16:27:40Z — попытка текста.
Отдельно: архивный `release-258191/live-diagnostics-2.58.191.json` несёт `captured_at_utc=16:44Z`,
что не соответствует его же содержимому (самое свежее значение мемов 16:28:16) — это дефект
метки **того архивного артефакта**, не продукта; файл не переписывается. Открытый вопрос —
какое поле питает отображаемое время; идёт фокусная проверка.

**LF-258192-02 — «Последних действий в журнале нет» — `DISPLAY_DEFECT_CONFIRMED_FIX_IN_FLIGHT`.**
Это дефект отображения обзора, а не вопрос фильтрации журнала. Строку даёт
`moduleLastEventLine(workspaceModule)`: для `mod_initiative` она возвращает пустую строку,
потому что `moduleHealthView` знает только `mod_vision`/`mod_sleep`/`mod_experience`
(`web/app.js:22882-22898`), а `moduleScopeErrorFor` для инициативы пуст (`web/app.js:22906-22917`);
ветка `v-else` печатает текст (`web/index.html:1884-1888`, шапка модуля — `1035-1042`).
Журнал при этом непустой: `GET /api/initiative/publications` по тому же чату вернул 327 строк
за 7 дней, вкладка отрисовала 40 строк и имеет **свой** текст пустоты «За выбранный период
попыток нет.» (`web/index.html:3164`). Исправление в работе; `P0IM-OV-LIST` остаётся `REVIEW`,
пока живой кадр не покажет реальные последние попытки.

## 5. Якоря: где доказательства и где разрыв

| Группа | Строк | Что это значит |
|---|---|---|
| VERIFIED с якорем на `bcc090a3` | 10 | привязано в этом проходе (S4 + NOETA) |
| VERIFIED только с преддеплойными якорями | 44 | доказательства действительны для своих кандидатов (`4c59a483`, `726736ee`, `a6884ad7`, `c087253d`), но не для выложенного SHA |
| открытые (не VERIFIED) | 58 | 47 `PENDING` + 11 `REVIEW` |
| **всего** | **112** | |

Из 44 преддеплойных строк 21 помечена `live_required` (поэтому в release-гейте даёт три
ошибки, а не две). Перенос этих якорей на `bcc090a3` — отдельное решение:
побайтовая идентичность тел патчей доказана (`deploy.md` §1), но перепривязка 44 строк
без повторной проверки была бы подменой доказательства; в этом проходе она не делалась.

Отдельное наблюдение по гигиене доказательств (не исправлялось, чтобы не подменять
доказательство): в старых S3-наблюдениях на `726736ee` прозой указаны снимки
`evidence/S3-OV/overview-filled-390x844-top.png` и `…-bottom.png`, которых в репозитории
**нет** — каталог `evidence/s3ov/` содержит только два `.md`. Поля `artifact_path` этих
строк указывают на существующие файлы, поэтому строгая проверка артефактов их пропускает;
но при перепривязке S3 снимки придётся снять заново.

## 6. Гейты — дословно

Команды (из корня проекта `C:\Code\Python\adminbot`), все три с картой
`plans/features/p0-init-meme-ux-diag/requirements-map.json`:

### 6.1 `--stage plan`

```
stage=plan inventory=42 manual=88 scoped=0 errors=0
```

exit 0.

### 6.2 `--stage review --slice S4-TRACE --candidate bcc090a358d81d510f473b0bba1647a1979113a2`

```
FAIL: P0IM-PB-LLM: mandatory not ['VERIFIED'] (got PENDING)
FAIL: P0IM-PB-FILTERS: mandatory not ['VERIFIED'] (got PENDING)
FAIL: P0IM-PB-STEP: mandatory not ['VERIFIED'] (got PENDING)
FAIL: P0IM-PB-LLM: mandatory not ['VERIFIED'] (got PENDING)
FAIL: P0IM-PB-MANUAL: mandatory not ['VERIFIED'] (got PENDING)
FAIL: P0IM-PB-ACCESS: mandatory not ['VERIFIED'] (got PENDING)
FAIL: P0IM-PB-VOCAB: mandatory not ['VERIFIED'] (got PENDING)
FAIL: P0IM-PB-COUNT: mandatory not ['VERIFIED'] (got PENDING)
stage=review inventory=42 manual=88 scoped=14 errors=8
```

exit 1. Восемь ошибок — ровно восемь оставленных строк (`PB-LLM` ×2 указателя, `PB-FILTERS`,
`PB-STEP`, `PB-MANUAL`, `PB-ACCESS`, `PB-VOCAB`, `PB-COUNT`); ни одной ошибки по шести
привязанным строкам, ни одной по кандидату/строгой проверке артефактов.

### 6.3 `--stage release --candidate bcc090a3… --deployed-commit bcc090a3…`

Инструмент печатает только первые 50 строк, поэтому ниже — дословно напечатанное, а полный
состав разобран в §6.4 (ничего не скрыто).

```
FAIL: P0IM-AC-NODUP: mandatory not ['VERIFIED'] (got PENDING)
FAIL: P0IM-OV-CARDS: no evidence bound to reviewed candidate
FAIL: P0IM-OV-CARDS: no candidate-bound evidence points to an existing repo artifact
FAIL: P0IM-OV-CARDS: live requirement lacks evidence for stage release
FAIL: P0IM-BAN-ENABLED: no evidence bound to reviewed candidate
FAIL: P0IM-BAN-ENABLED: no candidate-bound evidence points to an existing repo artifact
FAIL: P0IM-BAN-ENABLED: live requirement lacks evidence for stage release
FAIL: P0IM-AC-SETTINGS: mandatory not ['VERIFIED'] (got PENDING)
FAIL: P0IM-R0-PERCHAT: no evidence bound to reviewed candidate
FAIL: P0IM-R0-PERCHAT: no candidate-bound evidence points to an existing repo artifact
FAIL: P0IM-R0-PERCHAT: live requirement lacks evidence for stage release
FAIL: P0IM-AX-CONFIG: no evidence bound to reviewed candidate
FAIL: P0IM-AX-CONFIG: no candidate-bound evidence points to an existing repo artifact
FAIL: P0IM-AX-READY: no evidence bound to reviewed candidate
FAIL: P0IM-AX-READY: no candidate-bound evidence points to an existing repo artifact
FAIL: P0IM-AX-ATTEMPT: no evidence bound to reviewed candidate
FAIL: P0IM-AX-ATTEMPT: no candidate-bound evidence points to an existing repo artifact
FAIL: P0IM-AX-DELIVERY: no evidence bound to reviewed candidate
FAIL: P0IM-AX-DELIVERY: no candidate-bound evidence points to an existing repo artifact
FAIL: P0IM-OV-FALSEOFF: no evidence bound to reviewed candidate
FAIL: P0IM-OV-FALSEOFF: no candidate-bound evidence points to an existing repo artifact
FAIL: P0IM-OV-FALSEOFF: live requirement lacks evidence for stage release
FAIL: P0IM-ID-FINISH: mandatory not ['VERIFIED'] (got PENDING)
FAIL: P0IM-ID-MODE: no evidence bound to reviewed candidate
FAIL: P0IM-ID-MODE: no candidate-bound evidence points to an existing repo artifact
FAIL: P0IM-ID-CHILD: no evidence bound to reviewed candidate
FAIL: P0IM-ID-CHILD: no candidate-bound evidence points to an existing repo artifact
FAIL: P0IM-MM-MARKER: mandatory not ['VERIFIED'] (got PENDING)
FAIL: P0IM-OV-PERCHAT-CAUSE: mandatory not ['VERIFIED'] (got REVIEW)
FAIL: P0IM-R0-PERCHAT: no evidence bound to reviewed candidate
FAIL: P0IM-R0-PERCHAT: no candidate-bound evidence points to an existing repo artifact
FAIL: P0IM-R0-PERCHAT: live requirement lacks evidence for stage release
FAIL: P0IM-PB-LLM: mandatory not ['VERIFIED'] (got PENDING)
FAIL: P0IM-AX-HEALTH: no evidence bound to reviewed candidate
FAIL: P0IM-AX-HEALTH: no candidate-bound evidence points to an existing repo artifact
FAIL: P0IM-AX-CONFIG: no evidence bound to reviewed candidate
FAIL: P0IM-AX-CONFIG: no candidate-bound evidence points to an existing repo artifact
FAIL: P0IM-AX-HEALTH: no evidence bound to reviewed candidate
FAIL: P0IM-AX-HEALTH: no candidate-bound evidence points to an existing repo artifact
FAIL: P0IM-AX-READY: no evidence bound to reviewed candidate
FAIL: P0IM-AX-READY: no candidate-bound evidence points to an existing repo artifact
FAIL: P0IM-AX-ATTEMPT: no evidence bound to reviewed candidate
FAIL: P0IM-AX-ATTEMPT: no candidate-bound evidence points to an existing repo artifact
FAIL: P0IM-AX-DELIVERY: no evidence bound to reviewed candidate
FAIL: P0IM-AX-DELIVERY: no candidate-bound evidence points to an existing repo artifact
FAIL: P0IM-BAN-CONFLATE: mandatory not ['VERIFIED'] (got PENDING)
FAIL: P0IM-AC-NODUP: mandatory not ['VERIFIED'] (got PENDING)
FAIL: P0IM-OV-CARDS: no evidence bound to reviewed candidate
FAIL: P0IM-OV-CARDS: no candidate-bound evidence points to an existing repo artifact
FAIL: P0IM-OV-CARDS: live requirement lacks evidence for stage release
... and 117 more
stage=release inventory=42 manual=88 scoped=112 errors=167
```

exit 1.

### 6.4 Разбор 167 ошибок (полный состав, без остатка)

| Причина | Строк | Ошибок |
|---|---|---|
| строка не `VERIFIED` (47 `PENDING` + 11 `REVIEW`) | 58 | **58** |
| `VERIFIED`, но доказательство не привязано к `bcc090a3` — «no evidence bound» + «no candidate-bound evidence points to an existing repo artifact» | 44 | **88** |
| из них `live_required` — дополнительно «live requirement lacks evidence for stage release» | 21 | **21** |
| **итого** | | **167** |

Ни одной ошибки схемы, среза, графа, дублей `req_id` или строгой проверки Git-объекта/артефакта
по привязанным строкам нет. Гейт красный **только по составу доказательств**, а не по продукту.

## 7. Эпик НЕ завершён

`epic_done: false`. Блокеры: пять полностью открытых срезов (`S5-MEME`, `S5b`, `S6-FRESH`,
`S7-ACCEPT`, `A0-ARCH`), 8 открытых строк S4, `P0IM-BAN-CONFLATE`, `P0IM-ID-FINISH`/`ID-CONC`,
11 строк `S3-OV` в REVIEW и бухгалтерский разрыв якорей (§5). Выкладка 2.58.192 и привязка
двух срезов — готовый инкремент, а не завершение эпика.

## 8. Гигиена

Анализ и черновики шли в
`<GLOBAL_CONFIG>/WorkspaceData/runs/p0-init-meme-ux-diag/release-258192-pm/` (извлечённые
из `bcc090a3` `app.js`/`index.html`/тест и скрипты подсчёта). Каталог закрывается после
сдачи отчёта; в проект перенесены только три названных артефакта привязки.
