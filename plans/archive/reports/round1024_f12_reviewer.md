# Ревью F12 `summary-cover-model-compat-round1024` — Шаг 5, раунд 10.24

- **Коммит:** `ea04be9` (заявлено pytest 7612)
- **Ревьюер:** @Reviewer
- **Дата:** 20.09.2026
- **Артефакты:** `spec.md`, `ADR-1024-4.md`, `tasks.md`, `plans/current_task.md` UPD2 п.10/10.1 + UPD3 п.8
- **Верификация:** `git show ea04be9 --stat`, `git diff ea04be9^ ea04be9`; полный `pytest` на состоянии коммита; `node --check web/app.js`

## Статус

**Changes Requested**

Итог: универсальный payload и стиль-приоритет сделаны по контракту, инварианты целы, 7612 тестов зелёные. Но **R17 у probe-пути не выполнен фактически**: `body_excerpt` строится на `safe_text`, который маскирует только известные префиксы и env-секреты, а ключ image-провайдера, сохранённый через UI/PG (первоклассный сценарий UPD3 §6/BYOK), в маску не попадает. Если провайдер эхом вернёт ключ в теле ошибки — ключ утечёт и в серверные логи (journald/BetterStack), и в браузер админа. Это прямое нарушение spec §5.2 («без ключей»), ADR-1024-4 D3 («ключ никогда не возвращается») и R17. Плюс есть пробелы в тестах, дающие ложную уверенность. Без правок H1 выпускать нельзя.

---

## Findings

### [High] R17: `body_excerpt` probe не гарантирует отсутствие ключа

- **Файл:** `services/image_generation.py:461-485` (`_probe_post`), `:510-552` (`probe`)
- **Точка утечки:** `services/image_generation.py:475` — `text = safe_text(getattr(resp, "text", ""))`; далее `services/image_generation.py:544-549` — `log_external_api(..., body=body, ...)`; возврат — `ProbeResult(body_excerpt=body)` → `web/api/routes.py:1586` → JSON → тост/строка в браузере.
- **Дополнительная точка:** `services/image_generation.py:327-331` (`_request_with_retry`) — ретрай 429/503 логирует `body=getattr(resp,"text","")` через тот же `safe_text`.
- **Проблема:** `safe_text` (`services/external_log.py:116-132`) делегирует в `log_ring.sanitize` (`services/log_ring.py:65-84`), который маскирует только: литеральные секреты **из `settings`/env** (`_collect_secrets`, `:39-62`), `Bearer`/`bearer`, префиксы `sk-|gsk|or|tvly`, URI-креды. Ключ, сохранённый через UI в PG (`hot.get("keys.image_api_key")`, см. `config/settings.py:1316` и `services/param_catalog.py:617`), в `settings.IMAGE_API_KEY` может отсутствовать (`hot_config.get` не мутирует `settings`) — значит, в `_SECRETS` он не попадает. Провайдер, эхнувший ключ без узнаваемого префикса (например `{"error":"invalid api key abc123secret"}`), отдаст его в лог и в `body_excerpt`.
- **Почему это важно:** ключ (платный, BYOK) осядет в journald/BetterStack и будет показан в веб-строке/тосте. Это реальная утечка секрета (R17), а не теоретическая: критерий «провайдер может быть вообще любой» (UPD3 §8) прямо допускает ключи без префиксов, а BYOK-сценарий (UPD3 §6) — хранение именно в PG. В этом же коде есть штатное решение: `services/llm_probe.py:151 sanitize_error(text, api_key)` — вырезает переданный ключ явно.
- **Required fix:** в `probe()`/`_probe_post()` вырезать резолвнутый `key` из текста ошибки **до** `safe_text` (или прокинуть key в `safe_text`-обёртку): например `raw = str(resp.text or ""); if key: raw = raw.replace(key, "***"); body = safe_text(raw)`. То же — для `safe_text(str(exc))` в `probe()` (key в области видимости). В `_request_with_retry`-ветке probe либо не логировать `body`, либо прокидывать key для редакции. Добавить тест: ключ **без** известного префикса (например `abc123secret`), сохранённый только через `_patch_cfg(api_key=...)`, и ассерты `key not in result.body_excerpt` **и** `key not in caplog.text`.

### [Medium] UI-контракт не покрыт тестом; ослаблена структурная проверка

- **Файл:** `tests/test_round106_ia_smoke.py:448`
- **Проблема:** счётчик `JS.count("testable: false")` ослаблен 2 → 1, но компенсирующего ассерта не добавлено: ни `probeEndpoint: '/api/images/test'` у блока `image_generation`, ни подписи «Проверить подключение», ни ветки `if (b.probeEndpoint)` в `testBlock`. UI-требование UPD3 §8 и spec §3.5 покрыто лишь `node --check` (синтаксис).
- **Почему это важно:** поломка `probeEndpoint`/ветки probe/лейбла пройдёт все тесты — «зелёный» прогон перестанет что-либо доказывать про кнопку владельца.
- **Required fix:** добавить в `TestProviderBlockTestability` ассерты: наличие `probeEndpoint: '/api/images/test'` в JS, наличие `b.probeEndpoint ? 'Проверить подключение'` в HTML и упоминания `b.probeEndpoint` в `testBlock`.

### [Medium] R17-тест probe тавтологичен по маске

- **Файл:** `tests/test_summary_cover_model_compat_round1024.py:199-217`
- **Проблема:** проверка безопасности использует `sk-SUPER-SECRET-1234567890`, который ловится `_PREFIX_RE` в `sanitize` **независимо** от того, что ключ реально передан в probe. Тест не проверяет удаление именно резолвнутого ключа — он зелёный и при H1.
- **Почему это важно:** ложная уверенность в R17 закрывает глаза ровно на ту дыру, ради которой тест написан.
- **Required fix:** заменить/дополнить кейсом с ключом без узнаваемого префикса (см. H1) и проверкой логов (`caplog`), а не только `body_excerpt`.

### [Low] Имя kill-switch не соответствует области действия

- **Файл:** `config/settings.py:593-594`, `services/image_generation.py:207-225`
- **Проблема:** `SUMMARY_COVER_MODEL_COMPAT_ENABLED` меняет тело POST для **всех** путей (`_build_post_body` вызывается и из прямого чата «нарисуй», и из tool `generate_image`, `services/tool_router.py:1161`), а не только для обложки саммари. При откате «только обложки» откатывается вся генерация изображений.
- **Почему это важно:** оператор при инциденте с обложкой рубильником с именем «SUMMARY_COVER…» молча изменит поведение прямого чата.
- **Required fix:** либо переименовать в `IMAGE_MODEL_COMPAT_ENABLED` (с обновлением спеки/ADR/отката), либо явно задокументировать глобальную область в комментарии у флага и в spec §7.

### [Low] Рассинхрон текста 429 и лимита

- **Файл:** `web/app.js:3333`, `web/api/routes.py:1551`
- **Проблема:** generic-ветка catch для `testBlock` на 429 печатает «подождите 5 секунд», тогда как серверный лимит `/api/images/test` = 10с.
- **Required fix:** либо брать `detail` из ошибки, либо не хардкодить 5с в общем тексте.

### [Low] Параметр `chat_id` у `probe()` не используется

- **Файл:** `services/image_generation.py:510`
- **Проблема:** dead-param; в spec §5.2 допустим, но не нужен.
- **Required fix:** убрать из сигнатуры или использовать (прокинуть в логи).

### [Low] Тест kill-switch не проверяет байт-идентичность полного тела

- **Файл:** `tests/test_summary_cover_model_compat_round1024.py:72-77,102-121`
- **Проблема:** OFF-тесты проверяют лишь наличие `size`/`response_format`/`n`; лишнее добавленное поле регрессией не поймается, хотя spec §5.1 обещает «byte-identical».
- **Required fix:** ассерт полного равенства `body == {"prompt": ..., "model": ..., "n": 1, "size": ig._IMAGE_SIZE, "response_format": "url"}`.

### [Low] Probe тестирует сохранённую конфигурацию, а не поля карточки

- **Файл:** `web/app.js:3298-3313`
- **Проблема:** `probe()` резолвит `keys.image_api_key`/`models.image_*` из hot, а не значения полей формы; при вводе нового ключа без сохранения кнопка проверит старый/пустой. Формально соответствует spec D3 (тело `{prompt?}`), но UX владельца («кнопка в карточке, где вводится ключ») может обмануть.
- **Required fix:** либо зафиксировать в UI-подсказке «проверяется сохранённый ключ», либо поддержать передачу полей (вне текущей спеки — согласовать с @Architect).

---

## Контракт

### Чекбоксы по spec §9 / tasks.md

| Пункт | Статус |
|---|---|
| Тело POST строго `{prompt, model, n:1}`, без `size`/`quality`/`response_format` | ✅ `image_generation.py:215-225`; тесты `round1024:66-100` |
| Нет хардкод-карты «модель → параметры» | ✅ поиск по diff отрицательный |
| Kill-switch OFF → прежнее тело | ✅ `:222-224`; тесты `:72-77,102-121` (⚠️ неполный ассерт, L) |
| Приём `data[0].url` и `data[0].b64_json` | ✅ `:383-397`; тесты `:126-170` |
| Стиль приоритетен, visual режется до общего капа | ✅ `summary_generator.py:104-115`; тесты `:250-270` |
| Лог `style_present/style_len/visual_len/final_len` | ✅ `summary_generator.py:683-687`; тест `:273-301` |
| `POST /api/images/test` (RBAC global admin, rate-limit) | ✅ `routes.py:1570-1586`; тесты `test_webapp_api.py:1976+` |
| `probe()` без Telegram и без per-chat бюджета | ✅ `image_generation.py:510-552`; тест `:219-231` |
| `body_excerpt` R17-safe (без ключа) | ❌ **H1** — не гарантировано для PG-ключа без префикса |
| UI-кнопка + тост (успех/сырой текст) | ✅ `app.js:3298-3313`, `index.html:329-331,616-618` (⚠️ нет теста, M) |
| Причина отказа саммари — реальная (не только «unavailable») | ✅ `summary_generator.py:688-700`; тест `:273-301` |

### Инварианты

| Инвариант | Статус |
|---|---|
| physical-two-call | ✅ не затронут (F12 не трогает Stage-1/2) |
| egress `SEND_POINTS`/`SEND_ALLOWLIST` | ✅ новых send-точек нет |
| `parse_mode=None` plain-каналов | ✅ не изменён |
| R16 (аддитивное API) | ✅ новые поля `*_status/reason` в ProbeResult |
| R17 (логи/ответы без секретов) | ❌ **H1** |
| R18 (секреты не коммитить/цитировать) | ✅ в diff секретов нет |
| Δ DDL = 0 | ✅ миграций в diff нет |
| Δ каталога = 0 | ✅ `services/param_catalog.py` не менялся |
| F1/F2/F7/F8/F20/F21/F22 не сломаны | ✅ полный pytest на `ea04be9` — 7612 passed |

### Тесты

- Payload обеих моделей: ✅ `round1024:79-100` (`gptimage/ideogram/flux`).
- Обе формы ответа: ✅ `:126-170`.
- Kill-switch: ✅ `:72-77,102-121` (ассерт неполный, Low).
- Probe успех/ошибка/недоступность: ✅ `:175-245`.
- Стиль/усечение: ✅ `:250-270`.
- Логирование/причина: ✅ `:273-301`.
- UI-кнопка/тост: ❌ только `node --check`, поведенческих ассертов нет (Medium).

### Верификация прогона

- На рабочем дереве есть **посторонние незакоммиченные правки** (`web/api/memory_agi.py`, `services/dream_worker.py`, `tests/test_dead_extractor_paradigms_round1024.py`, `tests/test_settings_worker_sync_round1018.py`, `plans/backlog.md` — WIP следующей фичи). На грязном дереве падает `test_dead_extractor_paradigms_round1024.py::TestDeepSleepStatusApi::test_status_reason_from_last_skip` (`_ApiDb.count_paradigms() takes 1 positional argument but 2 were given`) — **к F12 не относится**.
- На состоянии коммита `ea04be9` (временный stash WIP, затем восстановлен): **7612 passed, 1 warning** — заявленное число подтверждено.
- `node --check web/app.js` → OK.

---

## Точный список правок (блокеры)

1. **H1:** `services/image_generation.py` — явная редакция резолвнутого ключа image-провайдера из тела ошибки probe (`_probe_post`, `probe`, retry-лог `_request_with_retry`), по образцу `services/llm_probe.py:151 sanitize_error`. Тест на ключ без известного префикса + проверка `caplog`.
2. **M:** `tests/test_round106_ia_smoke.py` — компенсирующие ассерты `probeEndpoint`/лейбла/probe-ветки; `tests/test_summary_cover_model_compat_round1024.py` — заменить тавтологичный R17-кейс.

Низкоприоритетные L1–L5 — устранить или явно задокументировать до следующего ревью.

Верни исправленную версию. Текущий код отклонён.

---

# Итерация 2 — повторный аудит

- **Коммит:** `3d4103a` (`fix(services,web,tests): раунд 10.24 F12 — вычистка резолвнутого ключа из body_excerpt, UI/R17-тесты (review iter1)`)
- **Учтено:** поверх влит F8-фикс `297d2ac` (`fix(...) F8 — корректная причина Empty State...`) — его правки/тесты F12 **не приписываются**.
- **Ревьюер:** @Reviewer

## Статус

**Approved**

H1 закрыт по существу, Medium/Low закрыты, регрессий нет. Инварианты целы, полный pytest 7619/0, `node --check` OK.

## Проверка High (закрыт)

- **Файл:** `services/image_generation.py` — добавлен `_redact_secret(text, secret)` (`:244-258`): буквальная замена резолвнутого ключа на `***` **до** `safe_text` (образец — `services/llm_probe.sanitize_error`).
- Точки применения:
  - `_probe_post` — `text = _redact_secret(resp.text, key)` (`:508-510`);
  - ретрай-лог `_request_with_retry(..., redact_key=key)` → `body=_redact_secret(resp.text, redact_key)` (`:334-358`), вызывается из `_probe_post` и `_generate_post` (defense-in-depth);
  - `probe()` — обе ветки исключений: `httpx.HTTPError` и generic (`:569-576`), `body=body` в F2-лог уже редакчен;
  - `_generate_post` — все три error-лога (status!=200, `bad_json`, `no_url`) (`:391-427`).
- **Ключ без префикса** (`abc123secretXYZ`) проверен реально:
  - `test_probe_error_redacts_unprefixed_key` — assert `secret not in result.body_excerpt`, `"***" in body_excerpt`, `secret not in caplog.text` (`tests/test_summary_cover_model_compat_round1024.py:200-233`);
  - `test_probe_retry_log_redacts_key` — 429→200: `secret not in caplog.text` (`:236-250`).
  - Тесты **не тавтологичны**: префиксных масок `sk-/gsk/or/tvly` в ключе нет, значит зелёный результат доказывает именно явную редакцию, а не `_PREFIX_RE`.
- Остаточных путей утечки ключа в probe не нашёл: URL POST ключ не содержит; `httpx`-INFO заглушен (`image_generation.py:55`); `logger.info("[image] probe ...")` печатает только mode/model/status/reason/chat_id. Закрыто.

## Проверка Medium (закрыто)

- `tests/test_round106_ia_smoke.py:451-468` — `test_image_generation_probe_contract`: `testable: true`, `probeEndpoint: '/api/images/test'`, `if (b.probeEndpoint)`, `this.api(b.probeEndpoint`, HTML-лейбл `b.probeEndpoint ? 'Проверить подключение'`, и подсказка. Счётчик `testable: false == 1` теперь компенсирован. `b.note` реально рендерится (`web/index.html:226,580`).
- Тавтологичный R17-кейс (`sk-…`) заменён кейсом с ключом без префикса (см. выше).

## Проверка Low (закрыто)

- **L1 (имя флага):** переименован в `IMAGE_MODEL_COMPAT_ENABLED` (`config/settings.py:597-598`), в комментарии прямо указана область «вся генерация изображений». Spec/ADR-1024-4/tasks на диске обновлены на новое имя.
- **L2 (текст 429):** хардкод «5 секунд» убран; catch показывает `e.message` = серверный `detail` из `ApiError` (`web/app.js:3336-3340`, `api()` `:1783-1789`), для `/api/images/test` = «повтор теста чаще 10 секунд».
- **L3 (`chat_id`):** задействован в `logger.info` probe (`image_generation.py:579-582`).
- **L4 (OFF byte-identical):** оба OFF-теста теперь сверяют **полное** тело (`round1024:72-77,102-121`).
- **L5 (UI-подсказка):** добавлен `note` про сохранённую конфигурацию (`web/app.js:554-557`), отрендерен.

## Инварианты

| Инвариант | Статус |
|---|---|
| physical-two-call | ✅ не затронут |
| egress `SEND_POINTS`/`SEND_ALLOWLIST` | ✅ новых send-точек нет |
| `parse_mode=None` plain-каналов | ✅ не изменён |
| R16 (аддитивное API) | ✅ |
| R17 (логи/ответы без секретов) | ✅ **закрыт** (H1) |
| R18 (секреты не коммитить) | ✅ в diff — только фейковый тестовый ключ |
| Δ DDL = 0 | ✅ миграций нет |
| Δ каталога = 0 | ✅ `param_catalog.py` не менялся; флаг env-only ClassVar |

## Тесты/прогон

- Целевые: `test_summary_cover_model_compat_round1024`, `test_summary_cover_round1023`, `test_image_generation_round1023`, `test_webapp_api`, `test_round106_ia_smoke` → **318 passed**.
- Полный: **7619 passed, 1 warning** (заявленное подтверждено; +7 к итерации 1, из них F12-прирост — 2 новых probe-теста + UI-тест, остальное — F8 `297d2ac`).
- `node --check web/app.js` → OK.

## Остаточные замечания (не блокирующие)

- **[Low, docs]** Старое имя `SUMMARY_COVER_MODEL_COMPAT_ENABLED` осталось в round-level планах: `plans/features/round1024-architecture.md:156` и `plans/backlog.md:127`. Авторитетные документы F12 (spec/ADR/tasks) обновлены; рекомендация — синхронизировать round-доки при следующем касании. Блокером не считаю.
- Прочие Low из итерации 1 закрыты.

**Вывод:** F12 `summary-cover-model-compat-round1024` — **Approved**. Можно двигаться дальше.
