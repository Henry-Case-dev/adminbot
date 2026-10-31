# W14 — Cover Style end-to-end + Summary L2 диагностика (P0): отчёт полосы Builder

Фича: `ASAP-SUMMARY-COVER-INTEGRITY-01` v2.1, §3 (Cover Style), §3.5 (Summary L2),
приёмочные сценарии 9–21 (`plans/current_task.md` §9.B).
База ветки: `evol/impl` @ `5da2b7b8` (полоса prompt-history закоммитила свой слайс
после старта моей работы; мои правки — поверх `5da2b7b8`, без коммитов).
Режим: только правки файлов и `pytest`; никаких `git reset/checkout/stash/clean/restore`
и коммитов. Чужие незакоммиченные изменения (screenshots `plans/features/evol/audit/evidence/*.png`
другой полосы) не трогал.

## 1. Что проверено (факт, не формулировка из отчёта)

| Требование ТЗ | Состояние до полосы | Итог |
| --- | --- | --- |
| §3.1 refs=[] не блокирует edit | `run_style_job`: `refs` пустые — проходят; но **все объявленные refs недоступны → жёсткий `reference_missing` + base** | исправлено: референсы строго опциональны |
| §3.1 partial refs | частично работало (`readable`-фильтр), но метки `optional_reference_unavailable` не существовало вовсе | добавлена метка + metadata/ids сохраняются |
| §3.1 prompt не утверждает приложенный знак | prompt собирался по **всем объявленным** refs, даже отсутствующим | исправлено: в prompt/manifest только фактически приложенные |
| §3.1 сохранность привязки | registry/API/seed не удаляют refs; удаление ассета — только явный admin `confirm=true` | регресс-тест на reload/правку другого поля |
| §3.2 реальный лимит 800/805 | лимит из 400 ответа записывался в capability, повтор при `exceeded` не отправлялся — **но манифест показывал старый capability-лимит (2000)**, а не обнаруженный 800 | исправлено: манифест показывает `observed_provider_400` |
| §3.3 различение `bad_json`/limit/timeout/capability/optional-ref | всё схлопывалось: `bad_json` → mca `style_failed`, один человеческий текст | добавлен `error_class` (5+ классов) в meta/manifest/аналитику |
| §3.3 transport-диагностика | `response_diag` (status/content-type/длина/ключи/request-id) собирался, но в манифест не попадал | прокинут в `manifest["provider_diagnostics"]` |
| §3.3 успех = реальное изображение | magic-bytes/format + bounded scene-check + атрибуция к job — уже было | подтверждено тестами, не ослаблено |
| §3.4 таймер | `started_at = created_at` для **любого** статуса; running/queued считались от создания | `started_at` только при реальном старте, `queued_at` отдельно, `elapsed_ms` на сервере |
| §3.4 stale preview | `preview_is_stale`/`preview_pair_current` были; статус job их не отдавал | статус успешного preview отдаёт `preview_revision_stale` + `style_revision` |
| §3.4 провал не стирает прежний preview | верно (пара пишется только при успехе) | регресс-тест |
| §3.3 Base fallback ≠ style success | `classify_cover_result`/`RU_STYLE_FAILED` корректны; в аналитике был только `base_fallback` + reason_code | добавлены `style_fail_reason`, `error_class`, `style_job_id` |
| §3.5 Summary L2 | Reviewer строгий (server-таксономия hard/soft, gate `l2_unusable`), L1 `bad_schema_version` — retryable | **не ослаблялось**; handshake версий проверен тестом |

## 2. Реальные причины (по коду и логам полосы)

1. **Refs были не «опциональны», а «всё-или-ничего».** `run_style_job` возвращал
   `_style_failed(reason="reference_missing")` при `profile.references` непустом и
   нуле читаемых файлов. Прод-наблюдение `medved_press → reference_missing →
   base_fallback` объясняется именно этим: файл референса физически недоступен
   (asset row/disk), и отсутствие **дополнительной** картинки отменяло Style Edit,
   хотя обязательный вход — Base bitmap.
2. **Prompt/manifest описывали неприложенные референсы.** `compile_style_prompt`
   и `_build_style_manifest` брали `profile["references"]` целиком, поэтому строка
   «референс: издательский знак» уходила провайдеру даже когда файла не было
   (риск ложного брендинга и лишние символы в жёстком лимите).
3. **Манифест «Resolved limit» врал после 400.** Лимит, реально сообщённый
   провайдером (`800`), писался в capability-кеш, но `_build_style_manifest`
   продолжал брать `caps.prompt_limit` (2000 `internal_config`) — Inspector видел
   не то ограничение, которое отклонило запрос.
4. **Один класс на все отказы.** `reason_class=bad_json` в проде покрывал и
   400 `prompt_too_long`, и невалидное тело 2xx, и (после 188 с) таймаут-подобное
   поведение. В mca-событии всё это уходило как `style_failed`, в UI — один текст.
5. **Таймер.** `started_at` = `created_at` (время создания строки), поэтому
   «Обработка…» считала очередь рабочим временем, а при отсутствии значения UI
   получал `now - 0` (наблюдаемые миллионы секунд).
6. **L2/L1 (не дефект кода).** Коды `reply_attribution_error`, `unsupported_claim`,
   `wrong_person_attribution` — hard/blocking по серверной таксономии; 6 blocking
   findings с ≥2 разными кодами и абзацами законно переводят прогон в
   `l2_unusable → LEGACY_FALLBACK`. L1 `bad_schema_version` — retryable-класс,
   промпт и валидатор согласованы по версии схемы (map v1 = 1, anchor v2 = 2,
   §95-v2 = 2). Ослаблять review/схему нельзя, дефект не подтверждён.

## 3. Что изменено (файлы и смысл)

### `services/cover_style_jobs.py`
* `ERROR_CLASS_*` + `edit_error_class(reason)`: `prompt_limit`,
  `invalid_provider_response`, `timeout`, `capability_unavailable`,
  `optional_reference_unavailable`, `rate_limited`, `provider_rejected`,
  `transport`, `local_io`, `provider_error`. Класс — доп. machine-факт;
  `reason`/mca-коды не переименовывались (umbrella `style_failed` сохранён).
* `_style_failed`: пишет `meta["error_class"]`, эмитит `fail_reason`/`error_class`
  в structured `usage_json` (для Analytics; `SAFE_LOG_FIELDS` и
  `_INSPECTOR_USAGE_FIELDS` расширены только enum-подобными полями).
* `run_style_job`: референсы резолвятся один раз; недоступные помечаются
  `meta["optional_reference_unavailable"]` (`declared`/`attached`/`unavailable`
  с `ref_id`/`asset_id`/`label`), `reference_missing` больше **не** терминальный
  выход; prompt и манифест собираются по `prompt_profile` (только приложенные).
* `_resolve_reference_details`: `ref_id`/`label` в диагностике (metadata не теряется).
* `prompt_diagnostics`: `references_declared`, `references_optional_unavailable`,
  `optional_reference_ids`.
* `_build_style_manifest`: `image_inputs` (Base/attached/declared/unavailable +
  `base_asset_id`), `optional_reference_unavailable`, `provider_diagnostics`
  (только R17-safe `response_diag`), `error_class`/`outcome`;
  `resolved_limit`/`limit_source` берутся из **обнаруженного** лимита
  (`observed_provider_400`), если провайдер его сообщил.
* `_manifest_mark_outcome`: `error_class` на последней попытке + итоговый.

### `services/cover_style_preview.py`
* `_status_timing`: `queued_at` = создание, `started_at` = первый
  не-`CREATED` stage (либо heartbeat), `elapsed_ms`/`elapsed_seconds`
  от реального старта (running — до now, terminal — до последнего stage),
  `timing_source`; отрицательный/неизвестный elapsed → `None`.
* `_public_status`: новые поля + `warnings[]` (`optional_reference_unavailable`
  с ref_ids), `error_class`, `prompt.references_declared/optional_unavailable`.
* `job_status`: для успешного (терминального) preview — `style_revision` и
  `preview_revision_stale` (старый пример не выдаётся за проверку новой ревизии).
* `preview_human_message`: разные тексты для `bad_json`/`timeout`/сети.

### `services/pipeline_analytics.py`
* `_cover_style_card`: `style_fail_reason`, `error_class`, `style_job_id`
  (из structured `usage_json` ивента) рядом с существующими
  `base_cover_ok`/`style_edit_ok`/`result=styled|base_fallback|no_cover`.

### Тесты
* Новый `tests/test_evol_cover_integrity.py` — 26 тестов по сценариям 9–21
  (офлайн, провайдер — моки; сеть не используется).
* Обновлён `tests/test_cover_style_wave_b_asap4.py`: прежний
  `test_reference_missing_exit` **противоречил** §3.1 v2.1 (требовал терминальный
  отказ при недоступных refs) — заменён на
  `test_reference_unavailable_is_optional_not_blocker`: Style Edit выполняется,
  edit вызван, причина отказа не выдумана.

## 4. Доказательства

* Целевые наборы: `tests/test_evol_cover_integrity.py` — **26 passed**;
  cover-набор `pytest tests -k cover` — **801 passed, 3 failed** (все три —
  pre-existing, см. §6); `-k "pipeline_analytics or inspector or l2_review"` —
  **154 passed**; связка cover/manifest/edit/recovery/preview/b04/analytics —
  **250 passed**.
* Сценарии 9–21 покрыты поштучно (имена тестов в модуле соответствуют
  «9/10/12», «11», «13/14», «15/16», «17/18», «19», «20», «21»).
* Диффы — только перечисленные сервисы и два тест-файла. `web/**` (UI),
  prompt-history, factcheck/evidence не трогались.

## 5. Честные ограничения

* **provider_live_unverified.** Реальный вызов `nano-gpt.com / qwen-image-3-pro`
  (прод-маршрут `edit`) не выполнялся: нужен живой ключ и оплаченный вызов.
  Проверено только офлайн: protocol/payload/классы/лимиты/манифест.
  Точная схема ответа именно этого gateway подтверждается только живым прогоном
  (сейчас поддержаны: binary `image/*`, `data[].b64_json`, `data[].url`,
  data-URL, async submit/poll — все с диагностикой при несовпадении).
* **Сохранность refs на проде.** В коде нет пути, который бы удалял
  `cover_style_references` при reload/deploy/reseed; удаление возможно только
  явным admin-запросом на asset `confirm=true`. Историческое исчезновение
  объяснимо потерей файла/строки ассета; теперь это **не блокер** и видно как
  `optional_reference_unavailable`. Проверить конкретный прод-инцидент по
  фактическим строкам без доступа к прод-PG нельзя.
* **run_id `20a1de993ec340339ac4a41be3751d31`.** Локальная БД — снапшот
  от 07.10.2026, записи прогона 31.10 в ней нет; прод-PG в этой полосе не
  читался (правила SSH/fail2ban). Вывод по L2/L1 сделан по коду/согласованности
  схем и логике gate, а не по живым строкам прогона.

## 6. Посторонние/пре-existing находки

* `tests/test_asap5_graphrag_recovery.py::test_warning_coalesced_not_repeated` —
  падение в `summary_memory` (коалисинг warning'ов): между вызовами меняется
  `status` (`building` → `superseded`), ключ коалисинга другой — ожидание теста
  устарело. Не моя область (summary memory), падал до полосы.
* `tests/test_cfg02c_image_isolation.py::TestSharedCeilingHonesty::test_usage_breakdown_separates_user_and_cover` —
  `RuntimeError: coroutine raised StopIteration` (исчерпан sync-mock в async-тесте).
  Не моя область, падал до полосы.
* `tests/test_summary_coverage_ledger_asap41.py::test_segment_permanent_failure_is_honest_degraded` —
  падает в общем прогоне `-k cover`, проходит изолированно: загрязнение
  порядка тестов, pre-existing.
* Наблюдение вне write-scope: `web/api/cover_styles.py::cover_asset_delete`
  удаляет ссылки на ассет при `confirm=true` — это явное действие админа, не
  тихий сброс; менять не требовалось.

## 7. Остаточные работы (не моя полоса)

* UI Test Style (кнопки/статусы/«В очереди»/stale-бейдж) — `web/**`, читает новые
  серверные поля `queued_at/started_at/elapsed_ms/elapsed_seconds/warnings/`
  `preview_revision_stale`.
* Живой прогон Style Edit на прод-маршруте (подтверждение реальной схемы
  ответа провайдера и реального лимита 800) — после безопасного окна.

## Итог

1. Style Edit больше не отказывает из-за отсутствующих необязательных референсов: Base + доступные refs + текст стиля идут в edit, отсутствие помечается `optional_reference_unavailable`, metadata не теряется.
2. Реальный лимит провайдера и класс отказа теперь доходят до манифеста/аналитики (`observed_provider_400`, `error_class`), идентичное «805 при 800» тело не переотправляется, а таймер считает от фактического старта.
3. Summary L2 не ослаблен: 6 blocking findings законно дают Legacy, L1-версия схемы согласована, Base-fallback и ошибка стиля различимы; живой провайдерский прогон остаётся `provider_live_unverified`.
