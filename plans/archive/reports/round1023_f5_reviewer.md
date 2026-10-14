# Ревью F5 `image-generation-tool-round1023` — раунд 10.23, ШАГ 5

- **Ревьюер:** @Reviewer (Senior Principal Engineer, quality gate)
- **Коммит:** `67278f2` (`feat(services,web,tests): раунд 10.23 F5 …`)
- **Дата:** 19.09.2026
- **Артефакты:** `spec.md`, `ADR-1023-5.md`, `tasks.md` (T-2136…T-2146), `round1023-architecture.md`, `plans/project.md`, `plans/current_task.md:64-70,101-120`.
- **Секреты:** значения ключа/пароля/SSH в отчёте не цитируются (R17/R18).

## Статус

**Changes Requested**

## Резюме (без смягчений)

Функционально фича собрана аккуратно: инструмент добавлен в конец 9-м, схема строгая, гейт работает, каталог и UI расширены без сдвига меню, бюджет и egress подключены, пин-тесты обновлены осмысленно. Но в фиче **есть Critical-дыра ровно по тому риску, ради которого писался ADR (R1)**: в GET-режиме ключ кладётся в query-строку `?key=…`, а `httpx` на уровне **INFO** логирует полный URL. Единственный sanitizer (`log_ring.sanitize`) навешен только на ring-буфер и BetterStack; обычный `console_handler` (systemd journald) **не** санитизируется. Итог — plaintext-ключ уезжает в журнал сервера. Пока это не закрыто, фичу в прод выпускать нельзя: это ровно «секрет утёк в логи», заявленный в spec §7 R1 как Critical.

## Findings

### 1. [Severity: Critical] Ключ из GET-режима утекает в журнал (journald/console) через INFO-лог httpx
- **File:** `services/image_generation.py`
- **Location:** `_generate_get`, строки 296–317 (ключ → `params["key"]` на 305–306; URL на 307; вызов на 308)
- **Problem:** в GET-режиме при заданном ключе (`keys.image_api_key` из PG или `.env IMAGE_API_KEY`) формируется `…/image/{prompt}?…&key=<secret>`. Реальный HTTP-вызов идёт через `httpx.AsyncClient`, а httpx на уровне **INFO** пишет строку `HTTP Request: GET <полный URL> "<HTTP-version> <status>"` (см. `httpx/_client.py:1025`). Роот-логгер в `bot.py:168` — INFO, `console_handler` (`bot.py:144-145`) **без** фильтра: `sanitize()` применяется только в `LogRingHandler.emit` (`services/log_ring.py:115`) и в `BetterStackHandler.emit` (`services/betterstack_handler.py:228`). То есть ключ попадает в stdout → systemd journal в открытом виде.
- **Доказательство (эмпирически, локальный сервер):** при `logging.basicConfig(level=INFO, handlers=[StreamHandler])` httpx выводит `HTTP Request: GET http://…/image/cat?model=flux&key=sk_… "HTTP/1.0 200 OK"` — полный ключ в консольном сообщении. Grep по репозиторию не находит ни одного `logging.getLogger("httpx").setLevel(...)` и ни одного sanitizing-фильтра на консольном хендлере.
- **Why it matters:** нарушен R17 и `plans/project.md:36` («ключи не логировать»). Ключ провайдера уходит в journald/BetterStack-archived логи, где его видят все, у кого есть доступ к серверу/логам; ротация ключа не поможет, утечка уже исторична. Это ровно R1-риск фичи.
- **Required fix (выбрать и реализовать явно):**
  1. **Убрать `?key=` из GET-режима полностью** — GET строго анонимный (соответствует UI-семантике: «в GET-режиме поле ключа блокируется»), либо
  2. оставить `?key=`, но закрыть оба вектора: `logging.getLogger("httpx").setLevel(logging.WARNING)` **и** обернуть `console_handler` в sanitizing-фильтр (`services/log_ring.sanitize`) — тогда ни один обработчик не печатает URL.
  Обязательно добавить регрессионный тест: перехватить логи при GET-вызове с заданным ключом и утверждать, что ключ не встречается ни в одном сообщении. Текущий `test_get_url_and_no_key_leak` (`tests/test_image_generation_round1023.py:196-218`) наоборот **фиксирует** ключ в URL и не проверяет логи — как guard он не работает.

### 2. [Severity: Medium] Тест «нет plaintext-ключа» слепо пропускает весь `plans/`
- **File:** `tests/test_image_generation_round1023.py`
- **Location:** `test_no_plaintext_image_key_in_repo`, строки 444–456 (`skip = (..., "plans")` на 446)
- **Problem:** скан и так идёт по `git ls-files` (только трекаемые файлы), а untracked `plans/current_task.md` в него не попадает. При этом из скана исключён весь каталог `plans/`, а `plans/MEMORY.md` и `plans/backlog.md` — **трекаемые** (`plans/` коммитится по `plans/project.md:20`). Значит, если ключ когда-нибудь утечёт в трекаемый план/отчёт, guard его не увидит.
- **Why it matters:** guard от Critical-риска (R1) имеет слепую зону ровно там, где тексты пишут люди и где секрет цитируется чаще всего.
- **Required fix:** убрать `"plans"` из `skip` (untracked `current_task.md` и без этого не сканируется через `git ls-files`); fallback-ветка по директориям и так не обходит `plans/`.

### 3. [Severity: Medium] Риск двойной генерации и двойного списания бюджета на ключевике
- **File:** `services/direct_chat_service.py` (строки 673–680) + `services/image_generation.py` (строки 414–431)
- **Location:** пре-гейт инжектит `<image_result status="ok">`, но `generate_image` **остаётся** в `active_tools` на этот же ход
- **Problem:** на сообщение-ключевик изображение генерируется и отправляется пре-гейтом, а затем тул-цикл получает тот же набор из 9 инструментов. В канон Stage-1 (Δ канона = 0 по spec §5) правило «не вызывай `generate_image` повторно, если уже есть `<image_result>`» не добавлено, а в тексте блока такой инструкции нет. Модель может вызвать инструмент второй раз → второе платное изображение и второе списание `image_calls`.
- **Why it matters:** платный внешний вызов; на потоке ключевиков это систематическая двойная стоимость и спам картинками. Бюджет-лимит смягчает, но не устраняет.
- **Required fix:** добавить в текст блока явную инструкцию модели не вызывать инструмент повторно (например, «Изображение уже отправлено — повторно `generate_image` не вызывай»), либо на ход пре-гейта исключать `generate_image` из `active_tools` (передавать `image_generation_enabled=False`), оставив генерацию только одним путём. Покрыть тестом.

### 4. [Severity: Low] Пре-гейт необоснованно зависит от наличия `tool_router`
- **File:** `services/direct_chat_service.py`
- **Location:** `_image_pre_gate_block`, строки 1278–1280
- **Problem:** `maybe_handle_keyword` не использует роутер вообще (генерирует и шлёт сам). Guard `router is None or not hasattr(router, "dispatch")` отключает фичу там, где она работоспособна (прямой чат без tool-loop), вопреки spec §2.2 (условие — только «модуль ON»).
- **Required fix:** убрать зависимость от `tool_router` в пре-гейте либо документировать её как сознательную.

### 5. [Severity: Low] `b64_json`-фолбэк при «жёстком» `response_format:"url"` не задокументирован
- **File:** `services/image_generation.py`
- **Location:** `_generate_post`, строки 230–250 (ветка `item.get("b64_json")`)
- **Problem:** spec §2.3 требует жёстко `response_format:"url"` и брать `data[0].url`. Тихая поддержка `b64_json` — недокументированное отклонение (защитное, но всё же поведение вне контракта).
- **Required fix:** либо пометить в spec/ADR как сознательный defensive-fallback, либо убрать.

### 6. [Severity: Low] `.env.example` не обновлён под новые env-ключи
- **File:** `.env.example`
- **Problem:** `plans/project.md:29` требует плейсхолдеры в `.env.example`; новые `IMAGE_*` там не появились (проверено: секции нет). T-2146 (DevOps) закроет сервер, но репозиторный шаблон остаётся неполным.
- **Required fix:** добавить закомментированные плейсхолдеры (без реальных значений).

### 7. [Severity: Low] Пробелы в тестах (не тавтологичных, но неполных)
- **File:** `tests/test_image_generation_round1023.py`
- **Пункты:**
  - `test_send_photo_gets_bytes_not_url` (225–239): ассерт `"top-secret" not in str(captured["kwargs"])` по сути пустой — в `kwargs` нет ключа by design. Нет проверки, что байты, а не URL, идут именно из GET-режима при заданном ключе.
  - `test_registered_in_dispatch` (144–146) не проверяет реальную запись `"generate_image"` в `dispatch()`; вызов идёт напрямую `router._generate_image`. Маппинг реестра не покрыт.
  - Не покрыта интеграция пре-гейта (`direct_chat_service._image_pre_gate_block`) и OFF-ветка `active_tools` в прямом чате (в `test_tool_calling_round1015` проверен только дефолт-ON = 9).
- **Required fix:** добавить перечисленные тесты.

### 8. [Severity: Low] `image_calls` не виден в дашборде бюджета
- **File:** `services/worker_budget.py`
- **Location:** `get_day_summary`, строки 308–340
- **Problem:** метрика пишется и лимитируется, но в сводку (`global.calls/tokens`, `chats[].calls/tokens`) не выводится — расход на картинки не видно в UI бюджета.
- **Required fix:** по желанию/по спеку — вывести `image_calls` в сводку (иначе отметить как сознательно вне scope).

## Контракт: фактическая сверка

| Пункт | Статус | Комментарий |
|---|---|---|
| Секрет: нет plaintext в git | ✅ | Git-tracked скан — 0 совпадений; `current_task.md` untracked/gitignored; сид пишет только URL/model/GET (`config_migrations.py:284-322`); `pg_db._seed_settings` секреты не сидит (`pg_db.py:523-527`); маска `{configured,last4}` — существующий механизм (`services/chat_keys.py`). |
| Секрет: не в Telegram | ✅ | keyed-URL в `sendPhoto` не передаётся, шлются байты `BufferedInputFile` (`image_generation.py:392-411`). |
| Секрет: не в логах | ❌ **Critical** | см. Finding 1 (GET-режим → httpx INFO → console/journald). |
| Tool calling: 9-й в конец, первые 8 байт-в-байт | ✅ | `tool_schemas.py:264-282`; тесты `test_nine_tools_in_expected_order`, `test_generate_image_is_ninth`. |
| Схема: EN, `additionalProperties:false`, `required:[prompt]` | ✅ | `test_schema_strict`. |
| `active_tools` гейт (env И тумблер), OFF → 8 | ✅ | `resolve_module_enabled` (env AND catalog, per-chat); `active_tools(image_generation_enabled=False)` по умолчанию. |
| `factcheck_tools` не тронут | ✅ | `test_factcheck_tools_unchanged`. |
| Пре-гейт без форса `tool_choice` | ✅ | `tool_choice` нигде не форсируется, генерация детерминирована ключевиком. |
| Циничная отмазка при падении | ✅ | `IMAGE_GENERATION_FALLBACK_PHRASE` в блоке пре-гейта и в статусе инструмента; `test_keyword_fallback_block`. |
| Провайдер: POST `{base}/images/generations`, `response_format:"url"`, `flux` | ✅ | `test_post_hard_url_format`. |
| GET `/image/{prompt}` без `/v1` | ✅ | `_host_from_base`; `test_host_from_base`. |
| Таймаут/ретрай ≤1 на 429/503/лимит размера | ✅ | `_request_with_retry`, `IMAGE_MAX_BYTES`; тесты `test_retry_once_on_429`, `test_no_retry_on_401`, `test_too_large`. |
| Egress: `send_photo` + allowlist | ✅ | `telegram_send.py:89-98`, `SEND_ALLOWLIST`. |
| Бюджет: `image_calls`, per-chat лимит, исчерпание→без вызова, PG down→fail-open | ✅ | `worker_budget.py:265`, `consume(None,…)` → runtime-PG (`_resolve_pg`); тесты `TestBudget`. |
| Каталог Δ | ✅ | REGISTRY 441→446, Settings 411→416, categorized 416→421, GROUPS 92→95, mapped 90→93, TAB_RULES 20 (+0). Пин-тесты обновлены согласованно. |
| Вкладки/меню | ✅ | `models_images`/`keys_images`→«Провайдеры», `flags_module_images`→`TAB_MOD_DIRECT`; tma-menu-freeze не нарушен; новых вкладок нет. |
| UI: чекбокс GET блокирует ввод ключа | ✅ | `dependsOn`+`blockDependsOn` (`web/app.js:3094-3105`), `web/index.html:273-296`. |
| Инварианты: physical-two-call-pipeline, порядок роутеров `bot.py` | ✅ | Коммит трогает `bot.py` только вызовом миграции (DI); роутеры/порядок не сдвинуты. |
| R16/R17/R18 | ⚠️ | R16 — ок; R17 — **нарушен логированием ключа** (Finding 1); R18 — отчёт чист (секрет не цитирован). |
| F1–F4 не сломаны | ✅ | Чистый worktree на `67278f2`: `tests/test_anticliche_round1023.py` — 59 passed; остальные F1–F4-тесты зелёные. |

## Тесты

Команда и результат (окружение и «грязное» рабочее дерево — см. примечание):

- `tests/test_image_generation_round1023.py + tool_schemas + param_catalog + frontend_tab_mapping + outgoing_guard_round1022` → **151 passed**.
- Полный прогон на **чистом worktree коммита `67278f2`** → **1 failed, 7231 passed**. Единственный падающий — `tests/test_history_cli.py::TestCliFts::test_scope_is_required` (окружение: нет untracked рантайм-файла `migrate_history`); он же падает и на родительском коммите `67278f2^` — **к F5 не относится**.
- `node --check web/app.js` → OK.
- **Важно:** в текущем рабочем каталоге есть **незакоммиченные** правки `services/anticliche_*`, `web/api/anticliche.py`, `tests/test_anticliche_round1023.py`; из-за них локальный полный прогон даёт 4–5 падений в F4-тестах. Это состояние дерева, **не** коммита `67278f2`. Ревью проверяло именно `67278f2` — 0 регрессий по F5.

## Точный список для @Builder

1. **Закрыть Critical (Finding 1):** убрать `?key=` из GET-режима **или** подавить INFO-лог httpx + навесить sanitize-фильтр на `console_handler`; добавить тест «ключ не появляется ни в одном лог-сообщении при GET с ключом». Не санитизировать только ring — консоль/journld тоже считается.
2. Убрать `"plans"` из `skip` в `test_no_plaintext_image_key_in_repo` (Finding 2).
3. Исключить двойную генерацию/двойное списание на ключевик: инструкция в `<image_result>` или `image_generation_enabled=False` в тул-сете на ход пре-гейта + тест (Finding 3).
4. Убрать ложную зависимость пре-гейта от `tool_router` (Finding 4).
5. Зафиксировать `b64_json`-фолбэк в spec/ADR или удалить (Finding 5).
6. Обновить `.env.example` плейсхолдерами `IMAGE_*` (Finding 6).
7. Добить тесты: dispatch-маппинг, пре-гейт-интеграция, OFF-ветка активных тулов в прямом чате (Finding 7).
8. (Опц.) Вывести `image_calls` в сводку бюджета (Finding 8).

После правки Critical-пункта — повторный прогон целевых и полного pytest, приложить подтверждение отсутствия ключа в логах.

Верни исправленную версию. Текущий код отклонён.

---

# Итерация 2 — ревью коммита `1fea163`

- **Коммит:** `1fea163` (`fix(services,web,tests): раунд 10.23 F5 — анонимный GET без утечки ключа, анти-двойная генерация, тесты (review iter1)`).
- **База:** поверх F4-фикса `4e05579` (в диффе `1fea163` — только 7 F5-файлов; F4-правки не приписаны).
- **Секреты:** значения не цитируются (R17/R18).

## Статус

**Approved**

## Что проверено по факту (не на словах)

### Finding 1 (Critical) — закрыт и подтверждён независимо
- **GET-режим анонимный:** `_generate_get` (`services/image_generation.py:306-317`) больше не принимает `key` и не кладёт `params["key"]`; вызов из `generate` (`:350`) без ключа. Новая ветка `params` содержит только `model/width/height/seed`.
- **httpx INFO подавлен:** `logging.getLogger("httpx").setLevel(logging.WARNING)` и в `bot.py:180-182`, и в `image_generation.py:47-49` (модульный side-effect на импорт `tool_router`). Независимая проверка: `getEffectiveLevel() == 30 (WARNING)`.
- **`SecretMaskFilter` реально маскирует до форматирования:** `services/log_ring.py:94-111` — мутирует `record.msg` (уже отформатированное) и `record.args=()`, всегда возвращает `True` (записи не отбрасываются); навешен на `console_handler` (`bot.py:147-150`).
- **Мой независимый прогон** (локальный HTTP-сервер + реальный `httpx` при принудительно включённом INFO + `SecretMaskFilter` на StreamHandler):
  - `HTTP Request: GET http://…/image/cat?key=sk_***` — ключ замаскирован;
  - `Authorization: Bearer ***` — токен замаскирован;
  - обычный лог `hello normal world` не изменён;
  - ни один из трёх тестовых секретов (`sk_…`, Bearer, реальный запрос) в выводе не найден.
- POST-путь кладёт ключ только в заголовок `Authorization`, а httpx заголовки не логирует; в `generate()` в логи идут лишь `mode/model/bytes/latency/reason` — ключа нет.

### Finding 3 — анти-двойная генерация
- `direct_chat_service.py:677-681`: пре-гейт ключевика вынесен из гейта `tool_router` (Finding 4) и выставляет `image_pre_gate_fired = bool(image_block)`; `:736-737`: при срабатывании пре-гейта `image_enabled = False` → `active_tools(..., image_generation_enabled=False)` не объявляет инструмент на этот ход. Один путь генерации и один `image_calls`. Тест `test_direct_chat_pre_gate_disables_tool` проверяет и отсутствие `generate_image`, и инъекцию `<image_result>` в user-content.
- В успешный блок добавлена инструкция «Повторно инструмент generate_image не вызывай» (`image_generation.py:440-442`).

### Finding 2, 4–8
- `"plans"` убран из `skip` secret-скана (untracked `current_task.md` и без этого не попадает в `git ls-files`) — Finding 2.
- Зависимость пре-гейта от `tool_router` удалена — Finding 4.
- `b64_json` задокументирован как сознательный defensive-fallback (`_generate_post`, docstring) — Finding 5.
- `.env.example` дополнен закомментированными плейсхолдерами `IMAGE_*` (без значений) — Finding 6.
- Тесты: `test_dispatch_mapping` (реальный `dispatch`), `test_pre_gate_*`, `test_direct_chat_image_off_eight_tools`, `test_get_url_is_anonymous`, `test_send_photo_gets_bytes_not_url` (проверяет `BufferedInputFile`/`filename`), `test_day_summary_reports_image_calls` — Finding 7/8.
- `get_day_summary` теперь отдаёт `image_calls` в `global` и по чатам — Finding 8 (аддитивно, регрессий нет).

### Инварианты
- Схема инструмента не менялась в этом коммите: `generate_image` по-прежнему 9-м, первые 8 байт-в-байт (`test_tool_schemas`, `test_tool_calling_round1015` — зелёные).
- `factcheck_tools` не тронут; `send_photo`+`SEND_ALLOWLIST` на месте; каталог Δ (446/416/421/95/93, TAB_RULES 20) не затронут (param_catalog в диффе нет).
- Порядок роутеров `bot.py` не сдвинут (только импорт фильтра и два `setLevel`); F4-код не тронут.

## Findings итерации 2

### [Severity: Low] `test_get_key_not_in_logs` фактически вакуумный
- **File:** `tests/test_image_generation_round1023.py:335-360`
- **Problem:** тест логирует через `logging.getLogger("httpx").info(...)`, но httpx уже на WARNING → запись не эмитится, `caplog.records` пуст, assert-цикл не исполняется. Проверяется косвенно «httpx заглушён», а не «фильтр маскирует».
- **Why it matters:** guard от Critical-риска формально проходит, но при снятии `setLevel` (регресс) тест останется зелёным, если фильтр перестанет маскировать.
- **Required fix (не блокирует):** явно утверждать `logging.getLogger("httpx").getEffectiveLevel() == logging.WARNING` и/или временно поднять уровень до INFO + навесить `SecretMaskFilter` на тестовый handler, доказав маскировку в самом сценарии (как в `test_secret_mask_filter_masks_keyed_url`).

### [Severity: Low] `SecretMaskFilter` не маскирует `exc_info` на консоли
- **File:** `services/log_ring.py:102-109`
- **Problem:** фильтр санитизирует только `record.getMessage()`; трассировки (`exc_info`) на консольный handler не проходят `sanitize`, тогда как LogRing и BetterStack маскируют `exc_text`. В F5 живого пути утечки нет (GET анонимен; POST-ключ в заголовке не попадает в исключения; `generate` логирует только имена типов), но defense-in-depth неполный.
- **Required fix (не блокирует):** по желанию маскировать и `record.exc_text`/`exc_info` в фильтре.

### [Severity: Low] Дрейф spec/ADR: GET описан как «ключ опционален»
- **File:** `plans/features/image-generation-tool-round1023/spec.md:75`, `ADR-1023-5.md:20`
- **Problem:** после фикса GET строго анонимный, а спека/ADR всё ещё упоминают `?key=`. Код корректнее спеки; артефакты отстали.
- **Required fix (не блокирует):** привести spec §2.3 / ADR §D1 в соответствие (отметить решение Human Gate #2 — анонимный GET).

### [Severity: Low] `generate()` резолвит ключ и в GET-режиме
- **File:** `services/image_generation.py:330`
- **Problem:** `key` вычисляется всегда, хотя в GET-режиме не используется (безвредно, в логи не идёт).
- **Required fix (не блокирует):** резолвить ключ только для POST-ветки.

## Тесты (итерация 2)
- Целевые (`test_image_generation_round1023` + `tool_schemas` + `param_catalog` + `frontend_tab_mapping` + `outgoing_guard_round1022` + `test_direct_chat`) → **318 passed**.
- Полный pytest → **7257 passed, 0 failed** (совпадает с заявленным). Единичный провал `test_betterstack_handler::TestNoRedirect::test_real_302_not_followed_by_opener` в промежуточном прогоне — подтверждённый флейк (ленточный порт/потоки): изолированно и при повторном полном прогоне проходит, к F5 не относится.
- `git show 1fea163 --check` — чисто. `node --check web/app.js` — OK (web не менялся в этом коммите).

## Вывод

Critical-риск R1 закрыт и **проверен независимо**: GET анонимен, httpx INFO заглушён, `SecretMaskFilter` реально маскирует ключи/Bearer и не портит обычные логи. Анти-двойная генерация реализована. Оставшиеся замечания — Low (усиление теста и синхронизация доков), не блокируют.

**Approved** @Orchestrator Код прошёл ревью. Можно двигаться дальше.
