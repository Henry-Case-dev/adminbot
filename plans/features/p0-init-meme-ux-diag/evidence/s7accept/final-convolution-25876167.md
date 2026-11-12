# Финальная свёртка `P0IM-AC-DONE` на 2.58.197 (итог эпика)

Эпик: `P0-INIT-MEME-UX-DIAG-CORRECTIVE` (`p0-init-meme-ux-diag`).
Дата: 2026-11-13 (system-local +12:00). Решение владельца: **закрыть эпик DONE
сейчас**, не ожидая естественной LLM-попытки; техническая часть `P0IM-PB-LLM`
подтверждена контролируемым прогоном, естественное production-событие вынесено
в отдельное **неблокирующее** наблюдение.

## 1. Что выложено

| Поле | Значение |
|---|---|
| Версия / ветка | **2.58.197**, `release/2.58.197` |
| Код (deployed) | `2587616759de31283585ffc105c91e7193c2e89e` |
| Код (Reviewer Approved) | `895764e27f6597421ac4f496853474392c95b48a` (docs `b5841bac`) |
| Тождество | `git diff 895764e2..25876167 -- services handlers web` пусто; отличается только `config/settings.py` (бамп версии) |
| Рестарт | `2026-11-12T09:41:37Z`, unit active, `NRestarts=0`, `/healthz` 2.58.197 |
| Схема / DDL | 47 / 0; новых флагов, настроек, промптов, моделей, маршрутов, планировщиков — 0 |
| Откат | `c134f93d` (2.58.195); снапшот `backups/predeploy-258197-20261112T094016Z.db` |
| Промежуточный 2.58.196 | `e8e2619b` выложен 08:55:40Z, откачен 09:08:28Z из-за живого дефекта OV-LIST; исправлен в 2.58.197 кодом `895764e2` |

Артефакты: `release-258197/deploy.md` (§1–§7), `postdeploy-read.txt`, `live-checks-2.58.197.json`,
`live-extra-2.58.197.json`, `live-ov-list-2.58.197.json`, `live-overview-2.58.197.json`,
`live-ui-2.58.197.json`, `settings-parity-2.58.197.json`, PNG обоих чатов,
`release-258197/binding-deployed.md`, `release-258197/gate-release-25876167.txt`.

## 2. Независимые ревью

| Артефакт | Вердикт | Что покрывает |
|---|---|---|
| `evidence/final-train/review-5d599ca1.md` | Approved | durability, честные поля, BAN-CONFLATE; `P0IM-ID-FINISH`, `P0IM-ID-CONC`, `P0IM-PB-VOCAB`, `P0IM-PB-COUNT`, `P0IM-PB-STEP`, `P0IM-BAN-CONFLATE` |
| `evidence/closure-train/review-931945b7.md` | Needs Fixes | блокеры `PB-ACCESS`, закрытые затем наблюдаемыми доказательствами |
| `evidence/closure-train/review-3b1c4ba9.md` | Approved | закрывающий поезд: `PB-ACCESS`, `PB-LLM`, `PB-MANUAL`, `OV-LIST`, `S6-EFFECTIVE`, `AC-MATRIX-FAIL`, `AC-NODUP`, `AC-MATRIX-CONFIG`, `AC-MATRIX-RBAC` + точечные re-review test-only фикса и live-фикса OV-LIST |
| `evidence/pb-llm/review-controlled-25876167.md` | Approved (техническая часть) | `P0IM-PB-LLM`: контролируемый прогон на коде выложенной 2.58.197 |

Три опоры ревью соблюдены: инспекция фактического кода кандидата, чтение утверждений
тестов (не имён), собственный риск-ориентированный контрпример с мутацией и возвратом
байтов (в `review-3b1c4ba9` — корреляционный режим Inspector и process-wide кольцо;
в `review-controlled-25876167` — no-op `record_provider_call`, тест падает на пустом кольце).

## 3. Интеграционные тесты на выложенном коде

`release-258197/deploy.md` §2 (прогоны на `25876167`): 7 файлов closure — **204 passed**;
`tests/test_initiative_coordination.py` — 56/4 (те же 4 предсуществующих, что на базе);
22 файла meme/initiative/publication/diagnostic — **519 passed / 4** (база 510/4);
`tests/test_webapp_js_unit.py` — 45 passed; `tests/test_web*.py` — 1539/11 (как на базе);
e2e: `ui_inspector_exact` 142/0, `ui_meme_ui_fields` 0, `ui_initiative_rework` те же 2
предсуществующих; JS `INITIATIVE-UI-OK` / `P0IM-OV-HONESTY-OK`.

Контролируемое доказательство `P0IM-PB-LLM`: test-only коммит `ee2ddeb5` поверх
`25876167` (`git diff 25876167..ee2ddeb5 -- services web handlers` пусто),
`tests/test_evol014_meme_initiative.py` — 62 passed, `test_speech_inspector_exact` 23,
`test_initiative_publications_api` 40, вместе **125 passed**. Захвачены реальные
`{job}#meme_summary` / `{job}#meme_joke`, identity provider/model/slot+reason,
prompt source/revision/sha12, Image API status/format/bytes, `tg_message_id`,
отсутствие полного текста в durable detail, Inspector correlation отдаёт записанный
текст, лишних LLM/Image-вызовов нет. Артефакт: `evidence/pb-llm/controlled-25876167.md`
(sha256 `2b8c48e79f274bac6bfeff23a0ce2f84c6a1109ecddd9d866699dc3a07458612`),
ревью: `evidence/pb-llm/review-controlled-25876167.md`.

## 4. Живые проверки 2.58.197

`release-258197/deploy.md` §4–§5 и живые JSON/PNG:

- **P0IM-OV-LIST — PASS**: в обоих чатах 5 строк обзора показывают «автоматически»,
  0 строк «способ не записан»; живой дефект 2.58.196 не воспроизводится;
- **PB-FILTERS**: 6 фильтров + `days=7/0/90` + пагинация — 200 и корректные выборки;
  `days=91`, `limit=0/500`, `offset=-1` → 422 (оба чата);
- **S6-EFFECTIVE**: `image_module` в `configuration.layers` с `layer=global`,
  `image_provider` available/configured/model=`qwen-image-3-pro`, `heartbeat` честно
  `ok=false, last_tick_ts=null`;
- **PB-ACCESS**: обычный Inspector отдаёт preview/hierarchy; корреляция → `not_recorded`
  без preview, маскирование, retention 24; не-админ → 403 оба чата;
- **AC-SETTINGS (parity)**: `config_global`, `overrides_map`, `prompts_catalog`,
  4×`prompt_versions`, `meme_settings` обоих чатов — sha256 до = после; расходится только
  волатильный `modules/3/gate/observed_at`; latest `updated_at` у всех 623 items — до релиза;
- **OV-SAMPLE**: «ВКЛ | ждёт: кулдаун…», «Последняя отправка: подтверждено · сообщение
  1211393 / 11112», действие «Показать попытку»; пункт «изображение создано, отправка
  отложена» — данные и причина есть, отрисовка покрыта JS/e2e;
- **AC-NODUP**: дельта 48 файлов, новых страниц/агентов/планировщиков/второго пайплайна/
  хардкода нет; отданный `app.js` побайтово равен проверенному;
- **AC-MATRIX-RBAC**: скан 68 414 символов на секреты — 0; не-админ 403; чужой чат текста
  не получает;
- **AC-MATRIX-FAIL**: покрыто тестами (204), в проде отказ провайдера не провоцировался;
- живые счётчики: `checked/decided/generated/published/delivered/pending` =
  323/323/1/12/13/5 (A) и 354/354/1/25/26/13 (B) — состояния не слиты.

## 5. `P0IM-AC-DONE` — свёртка критерия готовности

| Пункт критерия | Чем подтверждён |
|---|---|
| Для любого чата и механизма два пользователя с одинаковым доступом видят одно достоверное состояние | Живые payload/кадры обоих чатов на 2.58.197: одни и те же оси из одного ответа на чат; RBAC 403; чужой чат не смешивается |
| Включённое в кулдауне не называется выключенным | `configuration.enabled=true` + `readiness.waiting` в живом payload; карточка «ВКЛ … ждёт: кулдаун…» |
| Последняя попытка открывается как единая связная история от первого гейта до итога | Живой `GET …/publications/{id}`: цепочка этапов, `full_text`, `delivery`; одна строка = одна попытка (204/519 тестов на выложенном коде) |
| Неудачный `/meme` имеет точный или честно неизвестный исход | Ручной путь: 18 autodelete + 16 marker + 45 hotfix passed; живой маркер `released/expired`; живой запуск не выполнялся по запрету владельца (2026-11-12 §6) |
| Сохранённые настройки, промпты и квоты не изменены | `settings-parity-2.58.197.json`: все сохранённые поверхности sha256 до = после |
| Дополнительных LLM-вызовов ради диагностики нет | `review-controlled-25876167`: транспорт LLM вызван ровно 2 раза, Image API 1 раз, диагностика вызовов не создаёт; `review-3b1c4ba9`: identity/diagnostics аддитивны |

Свёртка не вводит новых требований: все 114 обязательных строк карты (77 уникальных
`req_id`) закрыты на выложенном коде и подтверждены существующими артефактами;
`release-258197/binding-deployed.md` — построчный индекс доказательств.

## 6. Неблокирующее наблюдение `WO-258197-PB-LLM-LIVE`

Естественная production-LLM-попытка **не наблюдалась** и **не помечена VERIFIED**:

- статус: `OPEN`, `blocking: false`, `owner: "agents"`, `owner_action_required: false`;
- контракт: `P0IM-PB-LLM` (техническая часть закрыта контролируемым прогоном);
- триггер: первая естественная мем-попытка на 2.58.197, дошедшая до LLM A/B
  (summary/joke);
- что читать: `GET /api/initiative/publications/{id}` → `chain[].facts.llm|prompt|api`;
  сверить provider/model/slot, prompt source/revision/sha12, факты Image API,
  `last_delivery`/`message_id`;
- что это даёт: подтверждение **production**-значений провайдера/модели и факта
  реального вызова; контролируемый прогон доказывает код и связку, но не конкретные
  production-значения (это прямо записано в honest limits обоих артефактов);
- владелец не является QA, ручных действий не требуется; наблюдение вне знаменателя
  и не удерживает ни эпик, ни очередь.

Отдельно сохраняется добровольное наблюдение S5b `WO-258194-S5B-DEFERRED`
(`publisher_not_bound → отложено → доставлено`) — оно тоже не acceptance-строка.

## 7. Итог

- Эпик **DONE**: инженерная реализация, независимое ревью, интеграционные тесты,
  выкладка 2.58.197, живые проверки и контролируемое доказательство `PB-LLM`;
- 114/114 обязательных строк (77/77 уникальных) — `VERIFIED`; финальный release-гейт
  на `25876167` — `errors=0`;
- единственный незакрытый пункт — необязательное производственное наблюдение
  `WO-258197-PB-LLM-LIVE` и добровольное `WO-258194-S5B-DEFERRED`; оба неблокирующие,
  без поручений владельцу;
- повторная выкладка не требуется и не выполнялась.
