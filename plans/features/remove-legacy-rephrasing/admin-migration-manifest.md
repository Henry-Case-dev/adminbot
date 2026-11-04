# RLR-05-ADMIN — migration manifest снятого rephrasing-пути

Источник: `plans/owner_inputs/2026-11-05-remove-legacy-rephrasing-v2.md`
§4 (таблица границ), §5 (BGS-05/BGS-06), §6.1–§6.4. Slice: `RLR-05-ADMIN`.

Машиночитаемое зеркало: `migration-manifest.json`. Источник истины для строк —
`services/param_catalog.py::LEGACY_REPHRASING_MIGRATION`; JSON собран из него,
паритет проверяет `tests/test_rlr_admin_manifest.py`.

Классы: `removed`, `retained_as_technical`,
`retained_for_explicit_transform`, `retained_for_specialized_pipe`,
`deprecated_compat`. Удаление НЕ делается по совпадению слова `guard`:
протокольные/структурные guard'ы остаются `retained_as_technical`.

## Ключи

| Ключ | Класс | Потребитель в рантайме | Что покажет UI |
|---|---|---|---|
| `SYSTEM2_DIRECT_ENABLED` | `deprecated_compat` | нет в новом маршруте; `config.settings.resolve_legacy_rephrasing_env_flag()` всегда `False`; call site удаляет RLR-02 | не показывать; старое `.env` читается без ошибки и игнорируется (env-only, истории/ревизий нет) |
| `prompts.direct_chat_synthesizer_system_prompt` | `deprecated_compat` | нет в новом маршруте: путь `_synthesize_direct_answer` отключён, reader удаляет RLR-02 | не показывать в Prompt Library; текст и история остаются читаемыми, значение не удаляется |
| `SYSTEM2_VALIDATOR_LOOP_ENABLED` | `retained_for_explicit_transform` | `negative_constraints.verbalize_validated` только при `form_contract` (явное редактирование/перевод) | не показывать (env-only) |
| `MCA_POSTPROCESS_FORM_GUARD_ENABLED` | `retained_for_explicit_transform` | `mca_gates.postprocess_form_guard_enabled` → form G1–G3 при наличии `form_contract` | «Форм-гард явного редактирования»; не обещает перегенерацию обычного ответа |
| `MCA_NUMERIC_CLAIM_GUARD_ENABLED` | `retained_for_explicit_transform` | `mca_gates.numeric_claim_guard_enabled` → numeric contract внутри явной трансформации | не показывать (env-only) |
| `MCA_RESPONSE_FRESHNESS_GUARD_ENABLED` | `retained_as_technical` | `services.response_freshness`: маркеры идемпотентности события/доставки + наблюдение совпадения текста | не показывать (env-only) |
| `EVIDENCE_EGRESS_GUARD_ENABLED` | `retained_as_technical` | `services.evidence_policy.egress_guard_enabled` → наблюдение `EVIDENCE_EGRESS_CHECK` (BGS-02), текст байт-в-байт | не показывать (env-only) |
| `EVIDENCE_ROUTING_POLICY_ENABLED` | `retained_as_technical` | `evidence_policy.policy_enabled` → pre-Writer маршрутизация/обязательность evidence | не показывать (env-only) |
| `SYSTEM2_FACTCHECK_ENABLED` | `retained_for_specialized_pipe` | фактчек: claims → evidence → verdict до финального текста | не показывать (env-only) |
| `SYSTEM2_SUMMARY_ENABLED` | `retained_for_specialized_pipe` | саммари/сон — отдельный продукт | не показывать (env-only) |
| `TELEGRAM_SEND_GUARD_ENABLED` | `retained_as_technical` | `outgoing_guard.sanitize_outgoing` — удаление настоящих машинных маркеров | не показывать (env-only) |
| `MCA_EGRESS_GUARD_ENABLED` | `retained_as_technical` | `mca_gates.egress_guard_enabled` — loopback/SSRF | не показывать (env-only) |
| `MCA_TOOL_DELIVERY_GUARD_ENABLED` | `retained_as_technical` | `mca_gates.tool_delivery_guard_enabled` — идемпотентность доставки инструмента | не показывать (env-only) |
| `MCA_SEND_RECHECK_ENABLED` | `retained_as_technical` | `mca_gates.send_recheck_enabled` — защита от повторной отправки события | техническая защита от повтора; не обещает переписывание текста |
| `MCA_CONTEXT_ANSWER_CACHE_ENABLED` | `retained_as_technical` | `mca_gates.context_answer_cache_enabled` — кэш ответов/идемпотентность | не показывать (env-only) |
| `ANTICLICHE_MAX_PATTERNS` | `retained_as_technical` | детектор клише — только диагностика (`anti_cliche_retries == 0`) | лимит детектора; не обещает повторную генерацию |

## Снятые поведения без отдельного параметра

| Поведение | Класс | Чем управляло | Что покажет UI |
|---|---|---|---|
| `system2_direct_two_call` (`tool final → JSON → prose`) | `removed` | `SYSTEM2_DIRECT_ENABLED` | нет переключателя |
| `duplicate_text_regeneration` | `removed` | `MCA_RESPONSE_FRESHNESS_GUARD_ENABLED` | нет переключателя |
| `form_freeform_retry` | `removed` | `SYSTEM2_VALIDATOR_LOOP_ENABLED` | нет переключателя |
| `numeric_freeform_postedit` | `removed` | `MCA_NUMERIC_CLAIM_GUARD_ENABLED` | нет переключателя |
| `evidence_egress_rewrite_drop` | `removed` | `EVIDENCE_EGRESS_GUARD_ENABLED` | нет переключателя |
| `public_speech_cut` | `removed` | нет ключа (модуль не читает env/config) | нет переключателя |
| `format_retry` | `removed` | `SYSTEM2_VALIDATOR_LOOP_ENABLED` + `FORMAT_GUARDS` | нет переключателя |
| `cliche_metatext_retry` | `removed` | `SYSTEM2_VALIDATOR_LOOP_ENABLED` | нет переключателя |

Фактическое состояние кода на кандидате (поле `current_state` в JSON):
`system2_direct_two_call` недостижим (флаг всегда `False`), но call site ещё
присутствует; `duplicate_text_regeneration` (`direct_chat_service.py:5414`,
LLM-вызов `duplicate_guard_retry`) и `numeric_freeform_postedit`
(`direct_chat_service.py:5328`, `apply_numeric_guard` на обычном финале)
**ещё активны** и снимаются в RLR-04. Класс `removed` — целевое состояние
(UI уже ничего не обещает), `current_state` честно фиксирует реальность до
снятия; после RLR-04 поле обновляется на снятое.

## Конфиг-совместимость и данные

- `SYSTEM2_DIRECT_ENABLED` остаётся читаемым для старых `.env`, но эффективное
  значение всегда `False`: `true/false/0/null` одинаково не включают двойной
  Writer. Ключ env-only и никогда не мигрировал в PG — истории/ревизий у него
  нет.
- Каталоговые ключи (`flags.*`, `limits.anticliche_max_patterns`) остаются в
  `REGISTRY` и в `bot_settings`; сохранённые значения и ревизии не удаляются.
  `removed`/`deprecated_compat`-ключи автоматически получают `hidden=True`
  (не показываются и не принимаются через config API), при этом значение
  остаётся читаемым по PG-ключу.
- Отдельный DML/скрипт миграции не нужен: схема БД не меняется, память и
  эмбеддинги не затрагиваются. Обратимость — обычный `git revert` (значения в
  PG не перезаписываются).
- Промпты владельца, их factory baseline, версии и история — не изменяются.
  `prompts.direct_chat_synthesizer_system_prompt` только скрывается из
  редактируемого каталога (значение и журнал версий остаются читаемыми);
  `prompts.direct_chat_verbalizer_system_prompt` не трогается — его читает
  живой L2.

## UI-волна (UR-F / PVR) — отложено

UI в `web/**` в этом срезе НЕ реализуется: поверхность принадлежит UR-F/PVR до
их слияния (§9.3). UI-волна обязана:

1. Не рисовать панель машинных флагов; использовать только человеческие
   формулировки §6.6: «Единое написание ответа», «Сохранение исходного смысла
   при явном редактировании», «Техническая очистка сообщений».
2. Не показывать ключи классов `removed` и `deprecated_compat`.
3. Для `retained_*` — показывать подпись из `migration_ui`, не обещающую
   перегенерацию/переписывание свободного ответа.
4. Не удалять сохранённые значения/ревизии; редакторы промптов и история
   версий остаются рабочими на мобильном и десктопе.
5. Диагностика одного ответа: L1 → tools → Writer → фактические deterministic
   ops → delivery, с причиной fallback/extra attempts (R-ADM.5).
