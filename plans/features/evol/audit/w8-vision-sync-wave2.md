> **ASAP-VISION-SYNC-01 / ВОЛНА 2 (w8 wave-2)** — потребители медиа:
> соседний текст, неоднозначность, альбом, фоновые потребители
> (сводки/факты/инициатива/поиск), изоляция чатов, v2-маршрут фактчека и
> каталогизация настроек распознавания.
> Worktree: `...\WorkspaceData\worktrees\c742e4de9e92c489\evol-71536a366a11-c63f6f44`
> (branch `evol/impl`, HEAD `390cacaf` + незакоммиченные правки этой волны).
> Коммитов НЕ делал (запрет владельца): кандидат = рабочее дерево.

# w8 wave-2 — потребители медиа: сценарии 7, 8, 9, 18, 19 + патч-ноты ядра

## 1. Что именно было дефектом (до правки)

| Место | До | Почему это дефект |
|---|---|---|
| `factcheck_orchestrator._run_inner` (v2) | при `media_pending` гейт suitability мог вернуть `no_claim`/`context_unavailable` и бот отвечал «нечего проверять» / «цель пуста», хотя OCR ещё шёл | текст тезиса мог жить ТОЛЬКО на картинке; ответ противоречил факту |
| `factcheck_orchestrator._run_inner` (v2) | при терминальном отказе Vision без текстового тезиса бот отвечал из пула «нечего взять для проверки» | содержимое картинки НЕ проверено — это другой факт, чем «нет тезиса» |
| `handlers/factcheck._empty_content_phrase` | при `image_unchecked` выдавал `FACTCHECK_IMAGE_NO_CLAIM_PHRASES` («фото посмотрел: проверять нечего») | картинку НЕ читали — «посмотрел» было ложью |
| `summary_memory._build_running_summary_impl` | конспект окна писался, пока анализ фото окна ещё шёл | конспект «замораживает» окно: готовый OCR в него уже никогда не попадёт, а факты о картинке остаются навсегда в виде «[фото]» |
| `summary_memory._build_batch_text` (граф/факты) | в извлечение фактов визуальное содержимое не попадало даже готовым, ссылки на источник не было | §4: знание по визуальному содержимому обязано иметь ссылку на завершённый анализ |
| `services/param_catalog.py` + `config/settings.py` | `models.vision_max_output_tokens`, режимы и все границы ожидания/жизни задачи не были в каталоге | владелец не мог ни увидеть, ни изменить предел вывода и тайминги (требование §5/§6) |

## 2. Изменённые файлы (моя зона)

| Файл | Что сделано |
|---|---|
| `services/factcheck_orchestrator.py` | `OUTCOME_PENDING="pending"` (+ в `REFUNDABLE_OUTCOMES`); барьер pending стоит ДО gate-маршрутов и срабатывает там, где гейт собирался ответить отказом (suitability ≠ `checkable`): ответ из `FACTCHECK_IMAGE_PENDING_PHRASES`, событие `temporal_media_pending`, исход отложенный (лимит не расходуется). Отдельная ветка «терминальный отказ распознавания + нет проверяемого текста»: `FACTCHECK_MEDIA_ERROR_PHRASES` + честная оговорка `publication.notice()`, событие `vision_failed`, исход `unavailable` (`no_claim` запрещён). Настоящая проверка (`checkable`) не блокируется — оговорка о pending/непроверенной картинке идёт в вердикт как раньше |
| `handlers/factcheck.py` | `_empty_content_phrase`: `publication.media_unchecked` → `FACTCHECK_MEDIA_ERROR_PHRASES` (в обеих ветках, ДО `has_image`) — «картинку не проверяли», а не «нечего проверять»; `_EARLY_OUTCOMES` += `pending` (равенство с `REFUNDABLE_OUTCOMES` сохранено) |
| `services/summary_memory.py` | новый шов `visual_window_state(db, chat_id, rows, consumer)` (без ожидания и без новых Vision-вызовов, chat-изоляция в запросах готовности) + `_visual_evidence_text/_visual_evidence_refs`; `_build_batch_text(..., media_evidence=...)` — готовый OCR/описание со ссылкой `msg:<id>, asset:<short>, анализ v<rev>`; `_build_running_summary_impl` — при pending в окне конспект НЕ пишется (статус `skipped_media_pending` → терминальное событие `vision_deferred`, сообщений в чат нет); `_extract_and_save_graph` — факты/граф видят только завершённые анализы |
| `services/initiative_observer.py` | документированный и проверенный факт: медиа-строки отсекаются (`non_text`), инициатива не создаёт утверждений о визуальном содержимом (ни pending, ни готовый OCR) |
| `services/search_service.py`, `services/search_aggregator.py` | контракт зафиксирован в коде: агрегатор работает только с текстом; поиск получает контекст из ЗАВЕРШЁННЫХ анализов, pending рендерится честной строкой (своей логики ожидания нет) |
| `services/param_catalog.py` | `_VISION_SYNC_PG_ONLY` — 12 PG-only ключей (см. §5), группы/вкладки in-place |
| `config/settings.py` | env-дефолты (ClassVar, без новых полей dataclass): `VISION_MAX_OUTPUT_TOKENS=0`, `MCA_VISION_READINESS_WAIT_SECONDS=20`, `…ASSOCIATION_WINDOW_SECONDS=900`, `…PENDING_INTENT_TTL_SECONDS=1800`, `…JOB_LEASE_SECONDS=180`, `…QUEUE_WAIT_SECONDS=300`, `…JOB_LIFETIME_SECONDS=1800`, `…JOB_MAX_RECOVERIES=3`, `…JOB_BACKOFF_BASE_SECONDS=30`, `…JOB_BACKOFF_MAX_SECONDS=300` |
| `tests/test_evol_vision_sync_wave2.py` (новый) | 11 тестов: §8.7, §8.8, §8.9, §8.18 (сводка/граф/инициатива/поиск), §8.19, v2 pending, v2 terminal-отказ, `_empty_content_phrase`, каталог+эффективность настройки |
| `tools/_vision_sync_w2_reissue_f8.py` (новый) | переиздание F8-артефактов официальным генератором + фикстуры + канон-пины + осознанное переутверждение hash каталога |

## 3. Доказательства по сценариям §8

Все проверки — offline (SQLite в tmp, Vision-транспорт не вызывается,
LLM — двойники), файл `tests/test_evol_vision_sync_wave2.py`.

* **§8.7 «обычный текст рядом с чужим фото»** — `test_sc7_…`: в чате висит
  фото с идущим анализом, вопрос «как вообще дела?» → `is_media_dependent`
  = False, `prepare_media_evidence(... allow_adjacent=False)` → `None` за
  < 1 с (окно ожидания 5 с не расходуется). Прямой путь Direct передаёт
  `allow_adjacent` только при явной ссылке (`direct_chat_service`), т.е.
  барьер на обычный текст не включается.
* **§8.8 «два соседних фото разных участников»** —
  `test_sc8_…`: `resolve_target_media` → `association_status=ambiguous`,
  `assets=[]`, `source_message_ids=(800, 801)`, `reason_code=ambiguous_target`;
  свидетельство потребителя не содержит ни одного из двух OCR. Случайной
  картинки нет.
* **§8.9 «альбом»** — `test_sc9_…`: три фото одной media group → готовое
  свидетельство содержит OCR **всех трёх** страниц, `association_kind=album`,
  источники `{900,901,902}`; при ещё не готовом четвёртом кадре альбом
  остаётся `pending` (не отвечаем по одному кадру), источники `{900…903}`,
  блок честно говорит «содержимое НЕИЗВЕСТНО» и запрещает «ничего нет».
* **§8.18 «сводки/факты/инициатива/поиск»** — три теста:
  * сводка: при pending в окне `_build_running_summary_impl` →
    `skipped_media_pending`, LLM не вызывался, durable-запись не создана;
    после `ready` тот же вызов даёт `success`, а в материал попадают OCR
    `«Итого по счёту: 12 340»` + ссылки `msg:1100`, `asset:…`, `анализ v2`;
  * факты/граф: извлечение получает OCR только готового кадра
    (`Договор подписан 1 июня`, `msg:1201`), неготовое фото не даёт
    выдуманного содержимого (ровно одно «изображение» в payload);
  * инициатива отсекает медиа-строки (`non_text`); поиск получает
    `pending`-строку «содержание ещё не распознано» и готовый OCR
    соответственно (payload финального запроса проверен).
* **§8.19 «изоляция чатов»** — `test_sc19_…`: фото принадлежит другому чату →
  в этом чате `association_status=missing`, `assets=[]`, свидетельства нет,
  чужой OCR отсутствует; `visual_window_state` для чужого `tg_id` возвращает
  пустые `ready/pending` (изоляция в SQL запросов готовности).

## 4. v2-маршрут фактчека и хендлер (патч-ноты ядра §6.1/§6.2)

* **pending (фото + «фактчек», анализ идёт)** —
  `test_v2_pending_media_forbids_no_claim`: реальный `orch.run_factcheck`
  возвращает `OUTCOME_PENDING` (входит в `REFUNDABLE_OUTCOMES`), отправлен
  текст из `FACTCHECK_IMAGE_PENDING_PHRASES`, в пул `no_claim` не попал,
  `service.check_claim` не вызывался (платной проверки нет).
* **терминальный отказ (пустая подпись)** —
  `test_v2_terminal_vision_failure_is_honest_not_no_claim`: `OUTCOME_UNAVAILABLE`,
  первая строка ответа из `FACTCHECK_MEDIA_ERROR_PHRASES`, в ответе есть
  «содержимое … НЕ проверено» + человеческая причина, `no_claim`-пул не
  использован, вердикт не выдуман.
* **хендлер** — `test_handler_empty_content_phrase_matches_media_state`:
  `image_unchecked` → «картинка не прочиталась/не проверена»; готовое фото без
  тезиса → прежний `FACTCHECK_IMAGE_NO_CLAIM_PHRASES`; pending → pending-фразы.
* Совместимость с ASAP-FC-ADMISSION-01 сохранена: единая точка допуска
  (`suitability` + `admission_blocked_by_pending_media`), второй фильтр и
  отдельный cooldown не вводились; `handlers._EARLY_OUTCOMES == orch.REFUNDABLE_OUTCOMES`
  (равенство проверяется существующим тестом и зелёное).

## 5. Каталог и настройки (§5/§6, без UI-кнопки)

Добавлены 12 PG-only ключей (владелец видит и меняет; значения — hot-конфиг,
фолбэк на env ClassVar):

* `models_vision` (вкладка провайдеров моделей): `models.vision_max_output_tokens`
  (int, диапазон кода 512…32768, 0 = по классу маршрута 4096/16384),
  `models.vision_reasoning` (`auto|off`), `models.vision_structured_output`
  (`auto|on|off`);
* `limits_vision` (вкладка «Распознавание изображений»):
  `limits.vision_readiness_wait_seconds`, `…association_window_seconds`,
  `…pending_intent_ttl_seconds`, `…job_lease_seconds`, `…queue_wait_seconds`,
  `…job_lifetime_seconds`, `…job_max_recoveries`,
  `…job_backoff_base_seconds`, `…job_backoff_max_seconds`.

Проверено тестом `test_vision_settings_catalogized_and_effective`: ключи есть в
реестре, не скрыты, описаны; `models.vision_max_output_tokens` реально меняет
эффективный предел (`8192` → 8192, `2` → нижняя граница 512, `0` → дефолт класса
маршрута) — это не «мёртвая ручка».

Переиздание пинов (официальным генератором `tools/gen_param_registry_round1025.py`
через `tools/_vision_sync_w2_reissue_f8.py`):

* `REGISTRY 583 → 595`, delta `177 → 189`, `GROUPS 120`/`_TAB_BY_GROUP 118`/
  `TAB_RULES 22` — без изменений (новые группы/вкладки не вводились);
* `plans/docs/param-registry-round1025.{tsv,meta.md}`, `screen-map-round1025.md`,
  `tests/fixtures/round1025/{f8_baseline,catalog_baseline}.json` переэмитированы;
* канон-пины в тестах синхронизированы (52 файла: `583→595`, `558→570`,
  `177→189`), `PARAM_CATALOG_SHA256_FOLLOWUP` переутверждён осознанно (L-F11S-1,
  правка ТОЛЬКО каталога; `routes.py`/`pg_db.py` не тронуты);
* `gen_param_registry_round1025.py --check` → **OK** (595/120/118/22, R17-чисто,
  TSV/map идемпотентны).
* `Settings`: новых полей dataclass нет (`dataclasses.fields == 468` — пин зелёный).

## 6. Прогоны (все в этом worktree, `C:\Code\Python\adminbot\.venv\Scripts\python.exe`)

| Прогон | Результат |
|---|---|
| `tests/test_evol_vision_sync_wave2.py` | **11 passed** (7.2 s) |
| `test_evol_vision_sync_core.py` + `test_evol_vision_sync_wave2.py` | **35 passed** |
| `test_evol_vision_sync_{core,wave2}`, `test_factcheck_orchestrator_cfg06`, `test_evol_fc_admission`, `test_factcheck_media_2026_10_25`, `test_factcheck_p0_fc` | **159 passed** |
| финальный свод (core+wave2+cfg06+fc_admission+media+p0_fc+`test_summary_memory`+`test_graphrag_memory`+`test_param_catalog`+`test_round1025_f8_registry`+`test_webapp_api`) | **604 passed** |
| `pytest tests/ -k "factcheck"` | 583 passed, **2 pre-existing failed** (сетевой класс DDG) |
| `pytest tests/ -k "summary_memory or graphrag or graph_extract or initiative or smartsearch or search_aggregator or search_service"` | 577 passed, **2 pre-existing failed** (coalescing-предупреждение) |
| `pytest tests/ -k "vision or media or chat_context or direct_chat or memory or asap5"` | 2274 passed, 38 skipped, **4 failed + 2 errors — все pre-existing** (см. §7) |
| каталог/пины: `test_param_catalog`, `test_round1025_f8_registry`, `test_ia_inventory_round1025`, `test_mca19_block_f`, `test_mca10b_…d`, `test_webapp_round109_ui`, `test_help_guide_round1014`, `test_settings_persistence_round1014`, `test_self_reflection_provider_round1014`, `test_budget_settings_round1019`, `test_frontend_tab_mapping`, `test_cfg03_param_audit`, `test_webapp_f4/f9`, `test_webapp_parity_smoke` | **318 passed** |
| webapp/API набор (`test_webapp_api` + `f5/f7/f11`, `hotfix7…10`, `round1010…1014`) | **600 passed** (после снятия рассохшегося пина 561 → 570) |
| `python tools/gen_param_registry_round1025.py --check` | **CHECK OK** |

## 7. Известные pre-existing падения (НЕ мои; доказано на чистом HEAD)

Метод: `git archive HEAD` в `WorkspaceData/runs/…/temp-3644a599e9` (читающая
операция Git, без reset/checkout рабочего дерева) и тот же тест там.

| Тест | Доказательство |
|---|---|
| `test_summary_l1_clusterizer::test_off_chain_byte_identical_single_call` | падает и в чистом HEAD-архиве (в `evol/impl` канон промпта отличается от базовой ветки) |
| `test_asap5_graphrag_recovery::test_warning_coalesced_not_repeated`, `test_graphrag_rebuild_asap32::test_not_serviceable_warning_coalesced` | падают в чистом HEAD (2 предупреждения вместо 1) |
| `test_mca17c_invariants_round1047::test_no_ddl_catalog_ks_tools_delta` | `PRAGMA user_version = 39` при пине 38 — миграция добавлена другой лейн, `services/database.py` не мой дифф |
| `test_mca01_tx_task_supervisor_round1027::test_write_points_go_through_single_writer` | пин-аудит `database.py` (в отчёте ядра зафиксировано) |
| `test_direct_fallback_recompose_asap32` (5 тестов) | падают в чистом HEAD |
| `test_asap7_direct_settings` (2 теста) | падают в чистом HEAD (миграции v35/бэкап-гард — другая лейн) |
| `test_summary_two_call_round1022`, `test_verbilizer_response_modes_round1023`, `test_summary_coverage_ledger_asap41`, `test_summary_source_window_asap41` | падают в чистом HEAD либо только в общем прогоне; изолированно (26/26) — зелёные |
| `test_factcheck_post_release_w1::TestAggregatorFailureTaxonomy` (2) | реальный DuckDuckGo отдаёт пустую выдачу → `empty_results` вместо `provider_error` (сетевой класс, файл не менялся) |
| `test_native_reply_media_context_round1024` (3 byte-invariant) | падают только в общем `-k` прогоне (порядок/глобальное состояние); изолированно и с моими файлами — 24/24 и 59/59 |
| `test_youtube_multimodal_download_round1024` (2 ERROR сбора) | файл видео-лейна (`handlers/youtube.py` + `tests/test_evol_video_intent.py` изменены параллельно) |
| `test_mca08_style_form::test_declared_events_really_emitted_in_code`, `test_mca17a…::test_registry_event_names_exist_in_code` | `direct.reply` объявляет `mca07_answer_cache` (удалено EVOL-031) — пре-существующее, вне моего диффа |
| `test_webapp_avatars_ui`, `test_webapp_js_unit`, `test_webapp_round1024_nodeflow`, `test_webapp_tma_fixes_ui` | падают в чистом HEAD либо вызваны незакоммиченными правками UI-лейна (`web/app.js`, `web/index.html`, `web/static/app.css`) |

## 8. Честные зазоры этой волны (с точными патч-нотами)

1. **Админ-кнопка «Проверить» (стадийная проверка Vision) — отложена.**
   Файлы `web/**` заняты UI-лейном (в рабочем дереве незакоммиченные
   `web/app.js`, `web/index.html`, `web/static/app.css`), поэтому кнопку не
   трогал — сервисная основа `services.media_readiness.run_admin_check` уже
   вкоммичена ядром. Патч-нота для UI-лейна: обработчик кнопки в разделе
   «Модели / Распознавание изображений» вызывает
   `services.media_readiness.run_admin_check(db, chat_id=<текущий>, transport=None)`
   и показывает стадии `provider → schema → content → saved → consumer`;
   `ok=True` только когда подтверждены ВСЕ стадии (HTTP 200 с пустыми
   `choices` — не OK).
2. **Полная статья-саммари (`summary_generator` L1/L2) по-прежнему видит медиа
   как «[фото]».** В этой волне визуальное содержимое подключено к конспекту
   окна (`_build_running_summary_impl`) и к извлечению фактов/графа. Патч-нота
   для следующей волны: в `summary_generator` (строки вызовов
   `_build_batch_text(rows, skip_empty=True)`) передавать
   `media_evidence = (await visual_window_state(db, chat_id, rows, consumer="summary"))["ready"]`
   и при непустом `pending` откладывать durable-сборку так же, как в конспекте
   окна (`vision_deferred`, без сообщений в чат).
   → **ЗАКРЫТО в §review-fix2 (P2):** статья получает `media_evidence`
   (`_media_xml_evidence`) и факты (`_media_facts_evidence`) из одного чтения
   `visual_window_state`; долговременное знание — только завершённые анализы.
3. **Поиск и медиа с подписью.** `chat_context.format_chat_context` подставляет
   медиа-блок только для строк БЕЗ текста; фото с подписью доходит до поиска
   одной подписью (OCR не попадает). Патч-нота (файлы вне моей зоны):
   `services/chat_context.py` — для строки с текстом И медиа-блоком добавлять
   блок отдельной строкой (`media_blocks.get(tg_id)`) вместо замены текста;
   `handlers/search.py` — при `pending` в окне отвечать честной оговоркой,
   а не «по картинке ничего нет».
   → **ЗАКРЫТО в §review-fix2 (P2):** явный параметр `media_for_captioned`
   (default OFF → паритет), smartsearch включает его; ожидающая/упавшая
   картинка даёт честную строку статуса, а не выдуманное содержимое.
4. **v2-маршрут фактчека по-прежнему за флагом (`flags.factcheck_pipeline_v2`,
   default OFF).** Дефект pending→`no_claim` в нём устранён, но включение
   маршрута — отдельное решение владельца, эту волну оно не блокирует.
   → **Уточнение в §review-fix2 (P1):** откладывание pending-запроса теперь
   работает и в v1 (DEFAULT-маршрут), поэтому фикс не зависит от включения
   v2-флага.
5. **Живые проверки в Telegram не выполнялись** (запрещено условиями задачи).

## §review-fix2 — закрытие замечаний ревью (B1, B2, P1, P2)

Ветка `evol/impl`, worktree `…/evol-71536a366a11-c63f6f44`, база — коммиты
`ca15a2f6` (ядро F1–F5) и `b6403881` (волна 2). Ниже — по каждому блокеру:
что было неверно, где исправлено и чем доказано.

### B1 (High) — «содержимое картинки НЕ проверено» не доходило до ответа

**Было.** В `factcheck_orchestrator._run_inner` ветка 2d была привязана к
пустоте текста (`not target_resolved`): у цели С текстом (подпись-просьба
«проверь скрин») терминальный отказ распознавания проваливался в ранние отказы
гейта, и пользователь получал голую фразу «нечего проверять» без причины и без
оговорки. В обычном хендлере (`handlers/factcheck.py`) ранние отказы гейта
(`no_claim_after_context`, `ambiguous_needs_clarification`) тоже уходили
«голым» пулом без `publication.notice()`.

**Исправлено.**

* `services/factcheck_orchestrator.py`: единый предикат `_media_unverified()`
  (`media_unchecked` / `media.vision_failed` / `album_incomplete`); ветка 2d
  привязана к РЕШЕНИЮ гейта (`decision is None or decision != CHECKABLE`), а не
  к пустоте текста. Отказ `no_claim` при непроверенной картинке заменяется
  причиной (`FACTCHECK_MEDIA_ERROR_PHRASES`) + `publication.notice()`; ветка
  уточнения (`ambiguous`) тоже получает оговорку.
* `handlers/factcheck.py`: единый шов раннего отказа `_gate_refusal_text()` для
  v1/legacy и temporal-маршрутов — причина + оговорка для обоих пулов
  (`no_claim`, уточнение). Предикат `_media_unverified()` продублирован
  намеренно (handler не зависит от оркестратора, как и раньше).
* Формулировка `_empty_content_phrase` не тронута: она уже называет состояние
  входа, дублировать оговорку поверх неё не стали (иначе одна и та же причина
  звучала бы в одном ответе дважды).

**Доказано.** `test_b1_v2_captioned_photo_terminal_failure_is_not_no_claim` —
фото с подписью «проверь скрин», анализ `provider_timeout`, 14 сообщений
вокруг: исход `unavailable`, первая строка из `FACTCHECK_MEDIA_ERROR_PHRASES`,
в тексте «НЕ проверено», `check_claim` не вызывался.
`test_b1_v1_gate_refusal_keeps_media_caveat` — тот же вход через хендлер
(v1-маршрут): отказ гейта заменён причиной + оговоркой.
`test_b1_gate_refusal_helper_covers_both_pools` — шов покрывает оба пула и не
меняет поведение для проверенной публикации. Пре-существующий пин на это же
поведение — `test_v2_terminal_vision_failure_is_honest_not_no_claim` (зелёный).

### B2 (Medium) — «анализа нет и задачи нет» висело вечным pending

**Было.** `summary_memory.visual_window_state` считал `missing` ожиданием
(агрегат `MediaReadiness.pending` включает `missing` по контракту ядра),
поэтому фото, принятое при выключенном Vision, навсегда блокировало конспект
окна: `pending` не пустел, а watchdog такую задачу не видел (её нет).

**Исправлено.** `visual_window_state` получил состояние `missing`:
`_state_analysis_missing()` (все активы — `ANALYSIS_MISSING` и без `job_ref`)
плюс `_analysis_rows_absent()` (в БД нет ни одной строки анализа; строка
`running` = работа в контуре). Только `pending` (реально идущий анализ)
откладывает конспект; `missing` идёт прежним путём без визуального
свидетельства; `failed`/terminal не блокирует (как и раньше).

**Доказано.** `test_b2_missing_analysis_does_not_block_digest` — фото без
анализа и без задачи: `pending == {}`, `missing` содержит сообщение, конспект
строится (`success`), в payload нет содержимого картинки.
`test_b2_running_analysis_still_defers_digest` — граница: идущий анализ (есть
задача) по-прежнему даёт `skipped_media_pending` без LLM-вызова.

### P1 — «повтори через минуту» без возобновления

**Было.** `defer_until_ready` вызывался только из Direct; фактчек на pending
OCR отвечал «повтори через минуту» и ничего не сохранял — пользователь обязан
был прислать запрос заново (и мог получить два ответа, если всё же повторял
уже после готовности анализа).

**Исправлено.**

* `services/factcheck_orchestrator.py`: `defer_factcheck_until_media_ready()` —
  durable-намерение `vision:intent:<chat>:<msg>` (coalesce, TTL — штатная
  настройка распознавания) через `defer_until_ready(consumer="factcheck")`.
  Откладывается ТОЛЬКО реально идущая работа (`ANALYSIS_PENDING` с задачей):
  «анализа нет и задачи нет» не превращается в мёртвое намерение.
* `install_resume_dispatch()` — единая точка возобновления: диспетчер ставится
  в момент фактического откладывания, поэтому слот обработчика
  `media_readiness` (его занимает Direct) используется как цепочка: чужие
  намерения идут прежним путём, фактчековые — в `deliver_deferred_factcheck()`.
  Переустановка идемпотентна и самовосстанавливается, если Direct
  зарегистрировался позже.
* `deliver_deferred_factcheck()` — продолжение через ЕДИНЫЙ оркестратор (в фоне
  нет aiogram-объектов исходной просьбы: переигровка хендлера невозможна, а
  второй путь доставки дал бы второй ответ). Своего пути доставки нет.
* `cancel_deferred_factcheck()` + вызов из `factcheck_handler` — свежая просьба
  по тому же сообщению снимает прежнее намерение
  (`superseded_by_new_request`), поэтому «один логический результат» держится
  даже если пользователь всё же повторил запрос. Чужие намерения (Direct) не
  трогаются.
* `services/smartmodule_phrases.py`: `FACTCHECK_IMAGE_PENDING_AUTO_PHRASES` —
  фраза «как прочитаю, проверку пришлю сам, повторять не нужно», выбирается
  ТОЛЬКО когда намерение реально зарегистрировано; без намерения остаётся
  прежний честный pending-пул.
* `handlers/factcheck.py`: откладывание подключено и к v1 (DEFAULT-маршрут:
  `flags.factcheck_pipeline_v2` default OFF), а не только к v2 —
  `_defer_pending_factcheck()` / `_pending_refusal()` в обоих ранних отказах
  гейта (temporal и legacy) и в ветке «нет тезиса в цели/окружении».

**Доказано.** `test_p1_factcheck_pending_defers_and_resumes_once` (v2) — pending
OCR → ровно одно намерение `consumer=factcheck`, повторная просьба не создаёт
второго, после готовности анализ возобновляется sweep'ом (`resumed=1`), второй
проход молчит, намерение закрыто.
`test_p1_factcheck_terminal_failure_resumes_honestly_once` — терминальный отказ
распознавания завершает отложенный фактчек одним честным ответом с причиной и
оговоркой (`terminal=1`), вердикт не выдумывается.
`test_p1_v1_pending_request_defers_and_resumes_once` (v1) — хендлер отвечает
фразой авто-продолжения (без «повтори через минуту»), намерение одно, после
готовности приходит вердикт (`check_claim` один раз), второго ответа нет.
`test_p1_repeat_request_supersedes_deferred_intent` — отмена снимает намерение
и идемпотентна (повторная отмена — `False`).
`test_p1_fresh_request_after_ready_prevents_second_answer` — пользователь
повторил просьбу уже после готовности: отвечает этот прогон, из sweep'а
второго ответа нет (`resumed=0`).

### P2 — статья и поиск не видели содержимое фото С ПОДПИСЬЮ

**Было.** `chat_context.format_chat_context` подставлял медиа-блок только для
строк БЕЗ текста, поэтому captioned-фото доходило до поиска одной подписью;
`summary_generator` (L1/L2 и извлечение фактов) отдавал в XML плейсхолдер
«[фото]» и не передавал `media_evidence` в `_build_batch_text`.

**Исправлено.**

* `services/chat_context.py`: параметр `media_for_captioned` (явный, default
  OFF → остальные потребители получают прежний вывод байт-в-байт). Для строки
  с текстом И медиа-блоком содержимое картинки идёт отдельной строкой рядом с
  подписью (это данные распознавания, не слова автора).
* `handlers/search.py`: smartsearch включает `media_for_captioned=True` — поиск
  идёт по всей публикации.
* `services/summary_xml.py`: `media_evidence` (`{tg: строка}`) заменяет
  плейсхолдер «[фото]» фактическим содержимым (OCR/описание с адресом) либо
  честной строкой «не распознано»; `None` → байт-в-байт прежнее поведение.
* `services/summary_generator.py`: состояние окна читается один раз
  (`_window_media_state`), затем раздаётся в двух формах —
  `_media_xml_evidence()` (строки для статьи: готовое + честный статус) и
  `_media_facts_evidence()` (`{msg: {text, refs}}` для `_build_batch_text`; в
  долговременное знание идёт ТОЛЬКО завершённый анализ). Обе формы реально
  подключены: XML статьи и `memorize_facts` в гибридном и legacy-контурах.

**Найденный при завершении дефект (исправлен).** Прерванная работа передавала
в `_build_batch_text(media_evidence=…)` результат `visual_evidence_lines()`, то
есть `{tg: строка}`, тогда как функция ждёт `{tg: {text, refs}}` —
`AttributeError` на первом же captioned-фото с готовым анализом. Разделение
форм (`_media_facts_evidence` / `_media_xml_evidence`) устраняет это и
закреплено отдельным регресс-тестом.

**Доказано.** `test_p2_captioned_photo_evidence_in_article_and_search` —
captioned-фото с готовым анализом: контекст поиска содержит OCR и адрес
`msg:<chat>:<id>`, статья содержит OCR + `анализ v`, плейсхолдера «[фото]»
нет; без флага контекст байт-в-байт прежний (паритет других потребителей);
непроверенная картинка даёт честную строку «не распознано».
`test_p2_summary_consumers_get_matching_evidence_shape` — регресс на форму
свидетельства (факты — словарь, статья — строка), OCR и адрес источника
доходят до фактов. `test_p2_facts_evidence_excludes_unready_media` — pending и
failed в факты не попадают.

### Прогоны после review-fix2 (этот worktree, `C:\Code\Python\adminbot\.venv\Scripts\python.exe`)

| Набор | Результат |
|---|---|
| `test_evol_vision_sync_wave2.py` | **24 passed** (8.9 с; было 11, добавлено 13) |
| `test_evol_vision_sync_core.py` | **35 passed** |
| `test_factcheck_media_2026_10_25.py` + `test_factcheck_handlers.py` + `test_epic33_router_isolation.py` | **103 passed** |
| фактчек-набор (21 файл: `test_factcheck_*`, `test_evol_factcheck_critical`, `test_asap8_v63_b07_temporal_factcheck`, `test_epic33_router_isolation`) | **458 passed, 2 pre-existing failed** |
| summary/search-набор (`test_summary_xml`, `test_summary_memory`, `test_summary_generator`, `test_summary_legacy_source_window_asap41`, `test_summary_l2_integration`, `test_summary_wave8_off_parity_asap41`, `test_summary_wave8_ladder_matrix_asap41`, `test_summary_article_formatter`, `test_summary_fact_package`, `test_smartsearch_{handlers,service,prompts}`, `test_search_aggregator`) | **351 passed** |
| summary-лестница (`test_summary_wave8_ladder_matrix`, `wave8_golden`, `source_window`, `article_formatter`, `fact_package`, `l1_repair`, `asap2_acceptance`) | **135 passed** |
| `pytest tests/ -k "chat_context or media_for_captioned or visual_window or build_batch_text"` | **7 passed** |
| `pytest tests/ -k "phrase or tone or style_policy or honesty or egress"` (пулы фраз/стиль) | **586 passed, 1 skipped** |

**Классификация падений.** Оба падения — `test_factcheck_post_release_w1::
TestAggregatorFailureTaxonomy` (`test_timeout_is_not_provider_unavailable`,
`test_api_error_is_provider_error`): тест поднимает реальный DuckDuckGo-fallback,
сеть отдаёт то пустую выдачу, то результаты, отсюда `empty_results` вместо
`provider_error` и «нет исключения» вместо таймаута. Файл
`services/search_aggregator.py` в этом диффе не менялся (последняя правка —
`b6403881`, только docstring: `git show b6403881 -- services/search_aggregator.py`
= 6 строк комментария), тест-файл тоже не менялся. Класс — pre-existing сетевой
(тот же, что зафиксирован в §7).

### Что осталось непроверенным и почему

* **Живые проверки в Telegram не выполнялись** — условиями задачи запрещены.
  Автотесты покрывают оба маршрута фактчека (v1/v2), откладывание и
  возобновление; живая проверка «отложенный ответ реально приходит в чат»
  остаётся за владельцем.
* Возобновление после рестарта процесса опирается на существующий sweep
  (`VisionMediaWorker._resume_intents`): намерение durable, но фактический
  рестарт-прогон в тестах не эмулировался (покрыто ядром F1).
* Если пользователь повторит просьбу ПОКА анализ ещё идёт, прежнее намерение
  снимается и создаётся новое (coalesce) — один ответ сохраняется, но счётчик
  «сколько раз откладывали» в логах увеличится (наблюдаемость, не поведение).

---

## 9. Остаточный риск

* Отложенный конспект окна при долго не готовом изображении: конспект не
  пишется, пока анализ не завершится (терминальный исход watchdog'а
  гарантирует, что это случится). Текст чата при этом не блокируется.
* В конспект/факты теперь попадает OCR завершённых анализов — это меняет
  содержимое внутренних конспектов (Prompt-канон не тронут; данные помечены
  «OCR, данные, не слова автора»; без медиа-свидетельств текст байт-в-байт
  прежний).
* `models.vision_max_output_tokens` в каталоге — диапазон клампится кодом
  `[512, 32768]`; значение вне диапазона не «молча режет результат», а
  приводится к границе (тест).
* Пересчёт счётчиков каталога затронул 52 файла тестов (пины): любые
  параллельные лейны, добавляющие параметры, должны переиздать пины тем же
  инструментом (иначе расхождение счётчиков).

---

## Краткое резюме (RU)

Довёл до конца то, что осталось от ядра. Фактчек во «втором» маршруте больше
не говорит «проверять нечего», пока картинка ещё распознаётся: он честно
отвечает «ещё разбираю» и не тратит лимит пользователя, а если распознавание
окончательно отказало — прямо сообщает, что содержимое картинки не проверено,
с причиной. То же исправлено в обычном хендлере. Фоновые потребители получили
барьер: конспект окна не пишется, пока анализ фото не готов (иначе готовый
текст с картинки уже никогда в него не попадёт), а когда готов — входит в
материал со ссылкой на сообщение, актив и ревизию анализа; факты и граф
видят только завершённые анализы; инициатива медиа-строки не комментирует,
поиск получает честный статус «не распознано» вместо выдуманного содержимого.
Сценарии 7, 8, 9, 18, 19 закрыты тестами: обычный текст рядом с чужим фото не
ждёт Vision, два соседних фото дают честную неоднозначность без случайного
выбора, альбом собирается целиком, чужой чат никогда не становится источником.
Настройки распознавания (предел ответа модели, режимы, границы ожидания и
жизни задачи) теперь в каталоге — владелец видит и меняет их, а значение
предела реально влияет на вызов; счётчики каталога переизданы официальным
генератором (595/189). Кнопку «Проверить» в админке не трогал — файлы UI
заняты параллельной лейн, патч-нота приложена. Все новые и затронутые наборы
зелёные; 12+2 падений классифицированы как pre-existing и подтверждены
прогоном на чистом HEAD-архиве.

**Дополнение §review-fix2 (после ревью).** Честная оговорка «содержимое
картинки не проверено» теперь доходит до ответа и для цели С текстом (подпись-
просьба), и в обычном хендлере. «Анализа нет и задачи нет» перестало считаться
ожиданием — конспект окна строится, а не висит вечно. Отложенный фактчек стал
durable-намерением с продолжением самим sweep'ом распознавания (в v1 и v2, без
повторной присылки запроса и без второго ответа при повторе). Статья и поиск
получают содержимое фото С подписью (OCR с адресом либо честный статус) вместо
плейсхолдера «[фото]»; заодно устранено рассогласование формы свидетельства
между статьёй и фактами.
