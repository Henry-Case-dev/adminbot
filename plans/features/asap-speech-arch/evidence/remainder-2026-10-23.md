# Остаток карты `asap-speech-arch` — 35 PENDING (PM-SPEECH-REMAINDER)

Лейн: `PM-SPEECH-REMAINDER`, writer (карта + этот файл). 23.10.2026, локальное время UTC+12:00.
Прод/SSH/сеть не использовались, полный pytest не запускался. Проверялись: файлы evidence в репозитории, `git show e4ee54f3:` для кода кандидата, имена тестов на HEAD, read-only гейты.

## 0. Что фактически осталось

В карте 120 inventory-строк (74 `required`, 35 `context`, 11 `duplicate`) + 41 manual. Required всего 115.
На момент лейна: **VERIFIED 80**, **PENDING 35** — ровно те 19 inventory + 16 manual, что разобраны ниже.
Кандидат карты и деплой: `e4ee54f3` (2.58.113). W1/W2/W3/W4 привязаны к `e4ee54f3` (`evidence/w4/binding-258113.md`).

## 1. Счётчики по классам

| Класс | Сколько | Что это значит |
|---|---:|---|
| `BIND` (сразу VERIFIED) | **0** | Ни одна из 35 строк не имеет готового артефакта, покрывающего её acceptance целиком. Выдуманных VERIFIED не ставилось. |
| `NEEDS_AGENT_CHECK` | **28** | Работа уже есть; нужен один адресный прогон/вердикт агента (Playwright, harness, матрица ревьюера, closing-report). |
| `NEEDS_IMPLEMENTATION` | **5** | Нужной функциональности/документа нет на кандидате `e4ee54f3`. |
| `NOT_YET_OBSERVED` | **1** | Окно наблюдения ещё не истекло. |
| `OWNER_OPTIONAL` | **1** | Личное наблюдение в реальном чате, metadata уже стоит; не блокирует DONE. |
| **Итого** | **35** | |

Немедленно закрыть (без новой работы) можно **0** строк. После **одного короткого шага** агента закрываются **12**: `T-UI-STATE`, `T-UI-TEXT`, `T-UI-MATRIX`, `T-GLASS-PERF`, `INS-HIERARCHY`, `INS-CONFLICT`, `ANTIPATTERN-MATRIX`, `REQ-EMBED`, `REQ-SCOPE`, `MIGR-CACHE`, `ARCH-ADR`, `TRACE-GRAPH` (последние два — написать отсутствующий документ).

## 2. Полная таблица 35 строк

Колонки: `req_id` · слайс · класс · доказательство / точный следующий шаг · владелец.

| req_id | slice | live | класс | состояние и следующий шаг | владелец |
|---|---|---|---|---|---|
| REQ-PROOF-EFFECT | INIT-LIVE | – | OWNER_OPTIONAL | Metadata `verification_tier=owner_optional`, `owner_policy_ref=plans/owner_live_checks.md`, `engineering_req_ids=[EVAL-MODES, EVAL-EGRESS]` уже стоят. Инженерные половины обязательны и PENDING. | Owner (добровольно) |
| REQ-PREFIX-SEP | P0-A | – | NEEDS_AGENT_CHECK | `w1/direct-runtime-assembly-w1.txt` даёт порядок и байты по стадиям (sha256_12), но exact assembled system в инспекторе и запрет dynamic-директив равного приоритета не показаны; `blocked_by: INS-EXACT`. | Architect + Reviewer |
| REQ-SCOPE | MIGR | – | NEEDS_AGENT_CHECK | Попараметрической матрицы chat>global>factory нет. Шаг: `pytest tests/test_add_exp_expression.py::test_chat_scope_inherit_label_isolation_and_reset tests/test_soul1_core_registry_api.py -q` + вердикт по expression/style/prompts/chat-блокам. | Builder + Reviewer |
| REQ-EMBED | P0-B | – | NEEDS_AGENT_CHECK | W3 подтвердил только Direct L2. Шаг: `pytest tests/test_soul1_composer_layers.py tests/test_soul14_layers_payload.py tests/test_expression_isolation_followup.py -q` + матрица писателей (initiative, factcheck-финал, summary, search/web/youtube, диагностики) и негатив для internal JSON. | Reviewer |
| ANTIPATTERN-MATRIX | TESTS | – | NEEDS_AGENT_CHECK | Артефакта с 11 строками §4 нет (`review-w1.md`/`review-r2.md` его не заменяют). Создать матрицу «антипример → проверка/негативный тест → вердикт». | Reviewer |
| MIGR-CACHE | MIGR | – | NEEDS_AGENT_CHECK | Hot-apply после записи не прогонялся. Шаг: `pytest tests/test_soul1_core_version_propagation.py tests/test_prompt_migrations.py -q` на кандидате + read-only сверка revision/NOTIFY. Прод-SSH не использовался. | Builder (локально) + DevOps |
| MIGR-VERIFY | MIGR | – | NEEDS_AGENT_CHECK | SELECT/независимый процесс/blob подтверждены deploy 2.58.111/2.58.113, но `inspector == payload` байт-в-байт не показан; `blocked_by: INS-EXACT`. | DevOps (read-only) |
| INS-TRACE | INSPECTOR | – | NEEDS_IMPLEMENTATION | На `e4ee54f3` инспектор отдаёт `run_id=correlation_id`, layers/versions, но нет per-call trace: model/provider, checksum после scrub/truncate/fallback retry. | Builder (INSPECTOR) |
| INS-EXACT | INSPECTOR | – | NEEDS_IMPLEMENTATION | В `web/api/speech.py` кандидата только `system_masked` (стр. 1442/1580); owner-debug exact assembled system отсутствует. | Builder (INSPECTOR) |
| INS-SKIPREASON | INSPECTOR | – | NEEDS_IMPLEMENTATION | Русские объяснения `few_shot`/`channel_output` не добавлены; машинные коды остаются основным текстом. | Builder (INSPECTOR) |
| INS-HIERARCHY | INSPECTOR | – | NEEDS_AGENT_CHECK | Иерархия и скриншоты `inspector_*` есть, click-through (текст/источник/редакция, без пустого скролла) не проверен: Playwright-проход Inspector + `pytest tests/test_soul1_composer_layers.py -q`. | Builder + Reviewer |
| INS-CONFLICT | INSPECTOR | – | NEEDS_AGENT_CHECK | Список конфликтов есть, покрытие классов (типографика/длина/мат-регистр/роль/chat-global/SOUL-*) не доказано: `pytest tests/test_soul1_composer_layers.py -q` + Reviewer-матрица классов. | Reviewer |
| T-PREVIEW | TESTS | – | NEEDS_AGENT_CHECK | Preview vs sent разделены тестом (`test_soul1_w6_speech_ui.py`), exact last request после адаптеров/fallback недоказуем без INS-EXACT; `blocked_by: INS-EXACT`. | Builder + Reviewer |
| T-I-COVERAGE | INIT-LIVE | – | NEEDS_AGENT_CHECK | Нужны initiative-прогоны I-01…I-09 с фиксацией action/delivery/target: в `w3/raw-*.json` поля `delivery`/`target_message_id` отсутствуют, действий `chat` нет. | Builder |
| T-UI-MATRIX | INIT-LIVE | – | NEEDS_AGENT_CHECK | `w4/ui-report.json`: viewports 320/360/390/430/768/1024/1280/1440/landscape, `failures: []`. Нет Windows fullscreen и Telegram-WebView-UA 390 (`w4/report.md:257` — реальный WebView не гонялся). Физическое устройство — добровольно. | Builder |
| T-UI-TEXT | INIT-LIVE | – | NEEDS_AGENT_CHECK | Отдельной проверки «длинная русская фраза + code token + URL во всех редакторах» нет: Playwright-инъекция строк на 320/390/1280, assert `scrollWidth<=vw` и отсутствие обрезки. | Builder |
| T-UI-STATE | INIT-LIVE | – | NEEDS_AGENT_CHECK | Состояния pristine/dirty/saving/saved/error/conflict и 409 покрыты UI-U07, но равенство сохранённого и загруженного после hard reload и в новом процессе не показано (в `ui-report.json` `reload` = 0). | Builder |
| T-GLASS-PERF | INIT-LIVE | – | NEEDS_AGENT_CHECK | Полигон не изменён (пиксельная сверка), контраст 9.26:1, paintMs<6ms/p95<40ms замерены; FPS до/после не измерялся (`w4/report.md:262`). Шаг: CDP-замер FPS baseline vs кандидат на 1280/390. | Builder |
| ADD-EXPR-INTENSITY | P0-D | – | NEEDS_AGENT_CHECK | W3 проверял только profanity; влияние wit/sharpness при фиксированном profanity не наблюдалось: harness 2 режима + негатив «Core-личность присутствует». | Builder |
| INIT-I01 | INIT-LIVE | – | NEEDS_AGENT_CHECK | Harness I-01: 3+ участника без вызова → `action=reply`, `delivery=chat`, `target=null` или silent/react. | Builder |
| INIT-I02 | INIT-LIVE | – | NEEDS_AGENT_CHECK | Harness I-02: возражение на `[msg:N]` → `delivery=reply`, `target_message_id=N`, не «самое свежее». | Builder |
| INIT-I03 | INIT-LIVE | – | NEEDS_AGENT_CHECK | Harness I-03: «лол»/флуд → react или silent без принудительного текста. | Builder |
| INIT-I04 | INIT-LIVE | – | NEEDS_AGENT_CHECK | Harness I-04: новая общая тема → `chat`, не reply из-за имён в окне. | Builder |
| INIT-I05 | INIT-LIVE | – | NEEDS_AGENT_CHECK | Harness I-05: удалённый reply-target → отмена/bounded reassess; есть только transport-тесты, initiative-прогона нет. | Builder |
| INIT-I06 | INIT-LIVE | – | NEEDS_AGENT_CHECK | Harness I-06: fake/чужой `message_id` → отказ доставки + диагностика. | Builder |
| INIT-I07 | INIT-LIVE | – | NEEDS_AGENT_CHECK | Harness I-07: старое сообщение бота → L1 учитывает свои сообщения и может промолчать. | Builder |
| INIT-48H | INIT-LIVE | **да** | NOT_YET_OBSERVED | Окно 48 ч: earliest `2026-10-25 13:14 UTC` (26.10 01:14 UTC+12) при сохранении 2.58.111; деплой 2.58.113 мог сбросить окно — уточнить датой рестарта read-only. Отсутствие событий не равно «работает». | DevOps (read-only) |
| EVAL-MODES | INIT-LIVE | – | NEEDS_AGENT_CHECK | Полной матрицы 3 режима × 3 жанра × 10 стимулов нет: W3 — 45 вызовов, мини-выборка (`w3-report.md:9`). Нужен harness ~270 вызовов с hash/model/temperature. | Builder |
| P0D-QUOTED | INIT-LIVE | – | NEEDS_AGENT_CHECK | s7-цитата с матом не выполнена из-за бюджета: один стимул с quoted source/user input/RAG/примером в трёх режимах + отсутствие forced insertion. | Builder |
| GOV-PENDINGLIVE | REPORT | – | NEEDS_AGENT_CHECK | Проверяется на closing-report: живое событие — отдельный PENDING_LIVE/PENDING_EXTERNAL с телеметрией и датой; epic не объявляется VERIFIED. | Orchestrator |
| ARCH-ADR | P0-A | – | NEEDS_IMPLEMENTATION | Файла ADR нет в `plans/features/asap-speech-arch` (только `source`, `requirements-map`, `slice-graph`, `reconciliation`): нужен `adr-l2-kept.md` — boundaries, DB keys, provider payload route, reverse constraints. | Architect |
| TRACE-GRAPH | MIGR | – | NEEDS_IMPLEMENTATION | Отдельного документа вызовного графа до provider API и Telegram `sendMessage` нет; `w0-inventory.md` его не заменяет. | Architect/Builder |
| REP-FORMAT | REPORT | – | NEEDS_AGENT_CHECK | Финального отчёта нет; формат (время/зона, IMPLEMENTED/TESTED/DEPLOYED/LIVE_VERIFIED/PENDING, коммиты/хеши, без секретов) проверяется на closing-report. | Orchestrator |
| REP-NOFAKE | REPORT | – | NEEDS_AGENT_CHECK | На closing-report проверить: недоступное = PENDING_LIVE/WAITING_EXTERNAL, не VERIFIED. Эта реконсиляция доказательством не является. | Orchestrator |
| DOD-FINAL | REPORT | – | NEEDS_AGENT_CHECK | DoD закрывается только closing-report после INSPECTOR/EVAL/48h. | Orchestrator |

## 3. Почему ни одна строка не стала VERIFIED

Проверялся не «текст похож», а наличие артефакта на кандидата `e4ee54f3` с покрытием acceptance целиком:

- W4-документы прямо ограничивают себя: Chromium-стенд, без реального WebView, без FPS, без проверки сохранения после reload (`w4/report.md:245–263`). Поэтому `T-UI-MATRIX/TEXT/STATE/GLASS` не BIND.
- W3 прямо ограничен: 45 вызовов, инициативный текст не снят, s7 не выполнен (`w3-report.md:9`). Поэтому `EVAL-MODES`, `P0D-QUOTED`, `INIT-I01…I07`, `T-I-COVERAGE`, `ADD-EXPR-INTENSITY` не BIND.
- В коде кандидата (`git show e4ee54f3:web/api/speech.py`) есть `system_masked`, но нет exact owner-debug payload и per-call checksum → `INS-EXACT`, `INS-TRACE`, а через них `T-PREVIEW` и `MIGR-VERIFY` блокированы.
- ADR и call-graph как файлы отсутствуют → `ARCH-ADR`, `TRACE-GRAPH`.
- `pristine/dirty/409` действительно закрыты (UI-U07 VERIFIED), но вторая половина `T-UI-STATE` (hard reload, новый процесс) не наблюдена.

## 4. Гейты (фактические прогоны, `--repo .`)

```
python C:\Users\main\.config\opencode\tools\requirements_gate.py check \
  --map plans\features\asap-speech-arch\requirements-map.json --stage plan --repo .
stage=plan inventory=120 manual=41 scoped=0 errors=0
EXIT=0

... --stage review --slice UI-U09 --candidate e4ee54f3 --repo .
stage=review inventory=120 manual=41 scoped=1 errors=0
EXIT=0

... --stage review --slice UI-P2 --candidate e4ee54f3 --repo .
stage=review inventory=120 manual=41 scoped=1 errors=0
EXIT=0

... --stage review --slice INIT-LIVE --candidate e4ee54f3 --repo .
stage=review inventory=120 manual=41 scoped=21 errors=25
EXIT=1
```

`INIT-LIVE` краснеет по двум разным причинам, и обе честные:
1. 15 PENDING-строк слайса (включая `INIT-48H`, который обязан быть `READY_FOR_LIVE`/`VERIFIED`);
2. **отдельная находка:** уже VERIFIED строки `INIT-I08`, `INIT-I09`, `INIT-TESTS`, `EVAL-EGRESS`, `T-DELIVERY-ERR` не имеют evidence, привязанного к `e4ee54f3` — их доказательства пришли с предыдущего кандидата. Это дрейф привязки, а не провал поведения; лечится тем же BIND-проходом по кандидату `e4ee54f3`, а не ослаблением гейта.

## 5. Что это значит для задачи

- Задача **не закрывается**: 35 открытых, из них 2 обязательных функциональных блока (`INSPECTOR` точный payload/trace/skip-причины) и обязательная eval-матрица.
- `progress_scope.json` **не менялся**: закрывать нечего, статус остаётся `BUILDING`.
- Наименьший путь к +12: (1) два документа — `adr-l2-kept.md` и call-graph; (2) один Playwright-прогон на четыре UI-строки + click-through инспектора; (3) матрица ревьюера на `ANTIPATTERN-MATRIX`/`REQ-EMBED`/`REQ-SCOPE`/`INS-CONFLICT`; (4) локальный hot-apply тест.
- Полный тренд остатка требует отдельного harness-прогона (`EVAL-MODES`, I-01…I-09, s7, wit/sharpness) — это один заход Builder, а не 10 мелких.
