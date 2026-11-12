# S7-ACCEPT — матрица приёмки эпика `p0-init-meme-ux-diag`

Эпик: `p0-init-meme-ux-diag`. Срез: **S7-ACCEPT** (приёмка на реальных данных).
Строки контракта: `P0IM-AC-MATRIX-*`, `P0IM-AC-POSTREL` (см. §3 — что заявлено).

## 0. База, кандидат и границы

| Поле | Значение |
|---|---|
| База | `dc699c72` (вершина одобренного S6-FRESH, ветка `init/meme-s6`) |
| Ветка среза | `init/meme-s7-accept` |
| Кандидат кода и тестов | `6d3b566e` |
| `tests/p0im_accept_matrix.py` | sha256 `205512b816c05038a9450d10d1165a8248b480670670937772d87bc720b08614` |
| `tests/p0im_accept_visual.py` | sha256 `95fa07684173174d838d32f9acb65066aadd4a995cb2feb5b4b4d7c4db9c65b9` |
| Выложено на проде | **2.58.194**, SHA `6c11fc08` |
| Страница отдана с | версия в DOM `2.58.194` (обоих чатов) |

Продуктовая поверхность не меняется: ни эндпоинта, ни таблицы, ни флага, ни
промпта, ни модели, ни настройки. Диффа в `services/`, `web/`, `handlers/` нет.

Прод читался **read-only**: одиночные SSH-коннекты (`mode=ro`, только
SELECT/PRAGMA), payload эндпоинта — с `127.0.0.1` подписанным initData (секрет
читался на сервере, в файл положен без печати и удалён после прогона), страница
и её API — обычным браузером. В чаты ничего не отправлялось.

## 1. Что добавлено этим изменением

### 1.1 Реальный визуальный слой (`tests/p0im_accept_visual.py`)

Браузер (Chromium, `playwright.sync_api`) открывает **отданную** страницу
`https://admin-bot.duckdns.org/web/#/modules/initiative` с реальным initData
владельца. Стаб — только Telegram-хост (SDK), API настоящий. Пять проверок:

| проверка | что измеряется |
|---|---|
| `AC-VISUAL-AXES-DESKTOP` | оба боевых чата, 1536×960: у обоих механизмов восемь строк (`config`, `layers`, `now`, `next`, `check`, `attempt`, `delivery`, `quota`) существуют, видимы и непусты; `documentElement.scrollWidth == clientWidth`; ни один элемент с id/датой не обрезан; штамп версии в DOM |
| `AC-VISUAL-AXES-MOBILE` | то же на 390×844 |
| `AC-VISUAL-STALE-DISCARD` | ответ диагностики чата A искусственно замедлен на 2.4 с (перехват в браузере, прод не тормозится), шапка переключена на чат B, пока ответ в полёте: карточки очищаются, уникальный `message_id`-sentinel из позднего ответа в DOM не появляется, после прихода ответа на экране данные чата B |
| `AC-VISUAL-FOREIGN-EXPIRED` | фаза A: подменённый `chat_id` чужого чата + sentinel `message_id` → карточка очищена, причина названа, sentinel отсутствует; фаза B: истёкший `manual_priority_until` при верном `chat_id` → ось readiness не изменилась, состояние не `busy` |
| `AC-POSTREL-BOTH-CHATS` | оба боевых чата: обзор, раскрытая трасса попытки, строка счётчиков/квоты, строка доставки, версия на странице = выложенной, SHA выложенной сборки записан |

### 1.2 Послерелизная фиксация (`P0IM-AC-POSTREL`)

Снято именно то, что показывает выложенный релиз: обзор и раскрытая трасса по
обоим чатам, строка доставки и счётчики/квота, штамп `2.58.194` в DOM и
сверка с выложенным `6c11fc08`. Артефакты пересъёмные: после следующего релиза
достаточно повторить команду из §6 — она сама сверит версию страницы с
выложенной.

### 1.3 Правило заявки строк

`SLICE_ROWS` больше не решает, что заявлено. Строка заявляется **только если
все её проверки прошли** (`row_claims`), иначе уходит в `rows_not_claimed` с
перечнем непройденных проверок и их статусов. Поэтому:
живой долг не закрывает строку «по факту наличия проверки», а браузерный слой
не заявляется, если он не запускался.

## 2. Матрица: 29 проверок

Прогон `matrix-prod.json` / `matrix-prod.md`: **29 проверок — 28 `passed`,
1 `not_yet`, 0 `failed`, 0 `blocked`; `run_ok=false`, `run_status=partial`.**

| № | проверка | вид | строки | статус |
|---|---|---|---|---|
| 1–3 | `AC-MATRIX-CONFIG-FACTORY/GLOBAL/CHAT` | code | CONFIG | пройдено |
| 4–5 | `AC-MATRIX-CONFIG-OFF/UNKNOWN` | code | CONFIG | пройдено |
| 6–11 | `AC-MATRIX-WAIT-*` (кулдаун полным путём, сообщения, квота, тихие часы, жребий, отложенный артефакт) | code | CONFIG | пройдено |
| 12 | `AC-EXPIRED-NOT-BUSY` (страж S6) | code | — | пройдено |
| 13–16 | `AC-DELIVERY-THREE-STATES`, `AC-TRACE-STOPPED`, `AC-TRACE-NEVER-STARTED`, `AC-CODES-UNKNOWN-READABLE` | code | FAIL | пройдено |
| 17 | `AC-TRACE-PUBLISHED` | code | — | пройдено |
| 18–19 | `AC-FRESH-TZ-SOURCE`, `AC-FRESH-SNAPSHOT-STAMP` | code | — | пройдено |
| 20–21 | `AC-RBAC-NONADMIN-DENIED`, `AC-RBAC-NO-CROSS-CHAT-LEAK` | code | RBAC | пройдено |
| 22 | `AC-LIVE-ENDPOINT-AXES` (оба боевых чата) | live | CONFIG | пройдено |
| 23 | `AC-LIVE-MESSAGE-ID` — **новое**: реальная доставка после релиза | live | FAIL | **пройдено** (`message_id=11107`) |
| 24 | `AC-LIVE-DEFERRED-CHAIN` | live | — (отдельный долг) | **не наступило** |
| 25 | `AC-VISUAL-AXES-DESKTOP` | visual | UI | **пройдено** |
| 26 | `AC-VISUAL-AXES-MOBILE` | visual | UI | **пройдено** |
| 27 | `AC-VISUAL-STALE-DISCARD` | visual | UI | **пройдено** |
| 28 | `AC-VISUAL-FOREIGN-EXPIRED` | visual | UI | **пройдено** |
| 29 | `AC-POSTREL-BOTH-CHATS` | visual | POSTREL | **пройдено** |

### Измеренные числа

| замер | 1536×960 | 390×844 |
|---|---|---|
| `documentElement.scrollWidth` / `clientWidth` | `1536 / 1536` (чат A и B) | `390 / 390` (чат A и B) |
| `body.scrollWidth` | `1536` | `390` |
| обрезанных элементов с id/датой | `0` | `0` |
| версия в DOM | `2.58.194` | `2.58.194` |
| оси обеих карточек | 8 строк на карточку, все видимы и непусты | то же |

| сценарий | наблюдено |
|---|---|
| гонка scope | переключение `-1004482340693 → -1002661910336` при ответе в полёте (задержка **2.4 с**); карточка сразу после смены: «нет данных»; sentinel `777000111` в DOM отсутствует; после прихода позднего ответа — данные чата B («может сработать сейчас») |
| чужой `chat_id` | `chat_id=-1002661910336` отклонён: карточка «нет данных», причина «Диагностика пришла для другого чата и отброшена — обновите экран», sentinel `777000112` отсутствует |
| истёкший маркер | ось не изменилась («ждёт: кулдаун, осталось 5 ч 29 мин»), состояние не `busy` |
| послерелизные строки | A: «подтверждено · 12.11 00:34 · чат -100448…», квота «1 / 3 · Осталось 2»; B: «подтверждено · 11.11 13:14 · чат -100266…», «0 / 3»; трасса: `пропущено` |

### Что осталось незакрытым

| проверка | причина |
|---|---|
| `AC-LIVE-DEFERRED-CHAIN` | живой цепочки `publisher_not_bound → deferred → delivered` ещё не было: отложенных строк 2, обе `claim_held`. Строку `MATRIX-FAIL` это не блокирует (её пункты покрыты пройденными проверками), но случай назван в её `not_covered`. Триггер: первый штатный «тик без привязанного бота» после релиза, затем повторный прогон матрицы |

## 3. Строки карты: что заявлено, а что нет

**Заявлены (все проверки строки пройдены):**

| строка | проверок | что закрыто | что НЕ закрыто этой матрицей |
|---|---|---|---|
| `P0IM-AC-MATRIX-CONFIG` | 12 | слои чата/общего/заводского, `enabled=false`/`null`, «разрешено ВКЛ + waiting» на шести ожиданиях, живой payload двух чатов | «100% вероятности, когда жребий не нужен», «отсутствие повода у L1» |
| `P0IM-AC-MATRIX-FAIL` | 6 | провайдерное исключение с этапом остановки, отсутствие строки, три состояния доставки, незнакомый код, реальный `message_id` доставки | ранние гейты без `job_id`, обрыв после LLM A/B, пустое изображение, конфликт отправок, старые неполные записи; живая цепочка `publisher_not_bound → deferred → delivered` пока не наблюдалась |
| `P0IM-AC-MATRIX-RBAC` | 2 | не-админ 403, без чата 422, ответ админа не смешивает чаты | скан «без утечки секретов», конкурирующие чаты/держатели брони |
| `P0IM-AC-MATRIX-UI` | 4 | реальные рендеры отданной сборки на двух чатах в двух вьюпортах, отсутствие прокрутки и обрезки, гонка scope, контрпример «чужой chat_id + истёкший маркер» | мобильный Telegram-клиент (проверен Chromium с мобильным вьюпортом), новые контрпримеры Reviewer под будущие изменения UI |
| `P0IM-AC-POSTREL` | 1 | послерелизные снимки двух чатов со штампом версии и сверкой SHA | Telegram-клиент реального устройства, продуктовый вердикт Reviewer по релизу |

**НЕ заявлены:**

| строка | причина |
|---|---|
| `P0IM-AC-MATRIX-MANUAL` | нужен живой ручной `/meme` при исчерпанной квоте и истечение `manual_priority_until` на проде; матрица проверяет только семантику истёкшего маркера |
| `P0IM-AC-DONE` | агрегатный критерий готовности собирается PM по всем срезам |

## 4. Почему отчёт не может разойтись с JSON

`write_result` пишет `result.json` → перечитывает с диска → рендерит
`SUMMARY.md`; сводка итерирует только `checks` и **пересчитывает заявленные
строки из проверок**. Пропавшая обязательная проверка → `absent_required_checks`
+ `run_ok=false`; неизвестный статус → `ValueError`.

Мутация (`mutation-log.txt`, `mutation-result.json`, `mutation-summary.md`):

```
MUTATION removed=AC-MATRIX-CONFIG-FACTORY checks_left=28 summary_rows=28 \
  claim_disappeared=True listed_as_absent=True rows_match=True
```

## 5. Прогоны

* `pytest tests/test_p0im_s7_accept_matrix.py -q -s` → **15 passed**
  (включая: строка заявляется только при всех `passed`; одна заблокированная
  проверка снимает заявку и называет её; `run_ok` не зелёный при долге;
  сводка только из JSON).
* `pytest tests/test_p0im_s7_accept_matrix.py tests/test_p0im_s6_fresh.py
  tests/test_initiative_publications_api.py tests/test_meme_init_diagnostics.py -q -s`
  → **97 passed**.
* Матрица с живым и визуальным слоями → 28 `passed`, 1 `not_yet`
  (`matrix-prod.json`), ~95 с.
* `--self-check` (без браузера) → 23 `passed`, 1 `failed`
  (`SELF-CHECK-DELIBERATE-FAILURE`), 1 `not_yet`, 5 `blocked`, код выхода 1
  (`self-check.json`).

## 6. Как повторить

```
python tests/p0im_accept_matrix.py --collect-snapshot snap.json        # read-only SSH
python tests/p0im_accept_matrix.py --out-dir out --snapshot snap.json \
    --visual --initdata-file <initdata> --visual-artifacts out/visual \
    --deployed-sha <sha выложенной сборки>
```

initData берётся владельцем один раз (подпись на сервере, файл не в репозитории
и удаляется после прогона); серверы браузера не поднимаются — страница
отдаётся продом, перехваты живут внутри playwright-контекста.

## 7. Артефакты

| файл | что доказывает | sha256 |
|---|---|---|
| `matrix-prod.json` | машинный результат: 29 проверок, 28/1 | `3009c0a73a8fe83f10ccea92876816425d4d08ba9f7841a3ba7a95a488de5ca9` |
| `matrix-prod.md` | сводка из JSON | `0320f254976ca06bf497ae23714523a2a6d4b274b620d13ddb1ee1664d727cad` |
| `self-check.json` | прогон с намеренным провалом | `fd295e8fa37cb7dcc1b7ec930b9967c29e7706b924989320311d668e11a33fb0` |
| `self-check.md` | сводка провального прогона | `635333c1cb9a6380fc512b0ab90a4bdb561cd81d7738733a61e8ae2d9d1f6791` |
| `prod-snapshot-2.58.194.json` | боевой снимок: журналы, `task_jobs`, `mca_bot_outputs`, endpoint двух чатов, `chats`, `healthz` | `be50a68772fdb0262fe2fa1a89e552ba46cc868dd504451796d3ab052e7fe5b9` |
| `visual/visual-measurements.json` | все замеры DOM (ширины, обрезка, sentinel, трассы) | `746f515eaba456457786739767f7d881d50b3cc39e1486fb8da82162f99330fe` |
| `visual/ac-visual-axes-desktop--1004482340693.png` | обзор 1536×960, чат A | `77f923c27d0fe3f8037647464625be8fd0e5ae4bddaf53b42bfdf1b299e87d59` |
| `visual/ac-visual-axes-desktop--1002661910336.png` | обзор 1536×960, чат B | `e0a7d4399f55b5a2da7905defac1c1b1ef516767ab213d24fea1d1fc56111345` |
| `visual/ac-visual-axes-mobile--1004482340693.png` | 390×844, чат A | `64cf250aca45580cec30cf4d27b701dfd3150e99b16696b5f3688016382b0c45` |
| `visual/ac-visual-axes-mobile--1002661910336.png` | 390×844, чат B | `096cd4c9fb39a2aa058567d5fe1a7f1887bb9384e204617c2e4811b7a7c70d80` |
| `visual/ac-visual-stale-after.png` | состояние после гонки scope | `e01e025964f5a211b64a8f3a2bd697594f7d403971d095af9381ad69f81b67ef` |
| `visual/ac-visual-foreign-chat.png` | чужой `chat_id` отклонён | `fed8151d56feb51451ec30c7e41e02970315696768ac6c45bac464e159955ed0` |
| `visual/ac-visual-expired-marker.png` | истёкший маркер | `86191085538329d59f75fa7b7656a25c368349d6805cd50943e47377287f31b2` |
| `visual/ac-postrel-overview--1004482340693.png` | послерелизный обзор, чат A | `0ccdf851c78191a577684af475fd12b1f839da6ec0f71e3d73f0cbce6aca1ada` |
| `visual/ac-postrel-overview--1002661910336.png` | послерелизный обзор, чат B | `98949f382923569fb0518fe2a20fe2f3dcbb0fde17beb1dbcd476bc7b2472dba` |
| `visual/ac-postrel-trace--1004482340693.png` | раскрытая трасса, чат A | `455dcc9e655c04fd0b3eab59ce93c8116198c6af7e7c4c7b937cf7ed0c4fa457` |
| `visual/ac-postrel-trace--1002661910336.png` | раскрытая трасса, чат B | `19c753123e8f7bdcb26383299055da005423e8c1a86d200ce31c7c26afbc2f8c` |
| `mutation-log.txt` | вывод мутации отчёта | `e8e140cf85fc423f4a4895cf645061f3906170e8f4e317a302c68a3cb5a79975` |
| `mutation-result.json` / `mutation-summary.md` | урезанный JSON и сводка из него | `70b31549c22972a64c7841138cf6b0371ffe2f471663869d1ab8cdc0044aa2dd` / `a0f64c87953f615ca7ee36a4dda7f376daaa2c61b33ebfb6c3301ae48676c9ad` |

Метаданные прогона (`matrix-prod.json` → `meta`): `candidate_sha=6d3b566e…`,
`matrix_script_sha256=205512b816c0…`, `visual_script_sha256=95fa07684173…`,
`snapshot_version=2.58.194`, `deployed_sha=6c11fc08…`,
`served_version=2.58.194`.

Стенд исполняет агент; от владельца ничего не требуется.
