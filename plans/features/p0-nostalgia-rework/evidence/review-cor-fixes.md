# REVIEW-PA5-COR — независимое ревью COR-01/02/03 (lan REVIEW-PA5-COR)

Кандидат: `6ddc5351` (task/pa5-cor, база `563aac43`; deployed prod = 2.58.137 @
`8adf5fa4` — кандидат НЕ задеплоен, это следующий релиз). Worktree ревью:
`C:\Code\Python\adminbot-wt-pa5cor-rev` (detached 6ddc5351). Изменений кода
ревью не вносило; evidence-файл — docs-only поверх кандидата.

## Вердикт: Approved (поведение COR-01/02/03 подтверждено на 6ddc5351)

Map-sync: строки COR-01/02/03 в requirements-map.json внутри кандидата
остаются PENDING по конвенции цепочки w→bind — bind-коммит после ревью обязан
поставить VERIFIED c `candidate_commit=6ddc5351` и сохранить needs-real-env
примечание COR-01 (MAP_SYNC_REQUIRED для Orchestrator, clerical).

## Леджер приёмки

| ID | Статус | Доказательство |
|---|---|---|
| COR-01 | VERIFIED (конфиг/формат) + needs-real-env (live 2 чата с разными внешними провайдерами) | Код + 2 теста (см. ниже); live-проба внешних провайдеров — вне sandbox, честно отмечена builder'ом в cor-fixes.md и подтверждена ревью |
| COR-02 | VERIFIED (детерминированный контракт маршрута/честности) | Словники удалены (grep: только комментарий); решение — за L1-планом; guard, denial+notice тесты. Семантическое КАЧЕСТВО L1 тестом не подменяется (ТЗ NOST-16-дисциплина соблюдена) |
| COR-03 | VERIFIED | `_sync_claim_with_outcome` на структурном статусе `classify_output`; substring-трюк внутри ошибки не даёт успеха (unit + end-to-end); оба call-site (691/1042) передают тот же `info`, что идёт в envelope |

## Проверка дефектов (counterexample-first)

### COR-01 — единая конфигурация / формат исходника
- Ключи строково совпадают: `image_generation.KEY_BASE_URL/MODEL/API_KEY` =
  `models.image_base_url` / `models.image_model` / `keys.image_api_key` =
  `capability_registry.IMAGE_BASE_URL_KEY/IMAGE_MODEL_KEY/IMAGE_KEY`. Одна
  цепочка `_chat_value` (per-chat override → hot → default) у проверки
  (`_build_image_edit`: base_url добавлен в тот же резолв; provider-label для
  `resolve_capabilities` = `ig._provider_from_url(РЕЗОЛВНУТОГО base_url)` —
  проверенная способность принадлежит провайдеру исполнения) и у исполнения
  (`_edit_image` → `capability_registry.chat_value(ctx.chat_id, …)`).
- Новых конфиг-систем нет (публичный `chat_value()` — обёртка существующего
  `_chat_value`). `_TOKEN_KEYS` + IMAGE_BASE_URL_KEY → кеш-инвалидация
  capability-состояний при смене base_url (stale-state counterexample закрыт).
- Формат: `_EDIT_SOURCE_SUFFIX_BY_MIME` (png/jpeg/gif/webp по сниффер-MIME
  `DownloadedImage.mime`; неизвестный → прежний `.png`). Тест воспроизводит:
  JPEG→.jpg, WebP→.webp, PNG без изменений; MIME data-URL edit-запроса
  соответствует фактическому формату. PNG-поведение не изменилось.
- Тест per-chat: override чата идёт И в `resolve_capabilities` (provider=
  host чата, base_url/model чата), И в `submit_edit` (adapter base_url,
  model, api_key) — один effective-набор.

### COR-02 — семантический edit-интент
- Словники `_EDIT_VERB`/`_EDIT_REMOVE`/`_EDIT_LOCATIVE_RE` удалены; grep по
  services: только упоминание в комментарии. Словесная edit-ветка детектора
  (шаг 3.5) удалена — `detect_action_intent` больше не возвращает
  INTENT_EDIT_IMAGE и не ветоирует по словам.
- Авторитет решения — L1-план (`capabilities_needed`): honesty-путь
  `_l1_capability_consistency` (edit requested + unavailable → denied:
  инструмент скрыт + правдивая `<capability_notice>` Writer'у).
- Structural guard: routing-fix принудительной генерации требует
  `"image_edit" not in requested` — create-интект по словам НЕ подменяет
  генерацией план, выбравший edit (тест test_word_intent_create_does_not_
  override_plan_edit). Обратный counterexample «план=generate, intent=create»
  — routing-fix работает как прежде (guard не сужает create-путь).
- Safe default при отсутствии плана: default non-edit handling (обычный ход,
  без edit-специфичных действий) — честный консервативный дефолт.
- Reply на изображение: L1 получает reply-контекст («ОТВЕТ НА (reply/цитата)»
  блок direct_l1 + reply-связи окна + vision-капшены) — семантическое решение
  обеспечено контекстом; детектор reply_text использует только для
  forwarded/негации (edit-классификации там нет — терять нечему). Отдельного
  детерминированного теста reply+edit-фраза нет — риск маршрута отсутствует
  (edit-ветки в детекторе нет), семантическое качество тестом не имитируется.
  Отмечено как NONBLOCKING-наблюдение к bind-коммиту.
- INTENT_EDIT_IMAGE / REASON_EDIT_REQUEST / edit_actionable /
  intent_blockers(edit) сохранены как структурный контракт (тест жив).

### COR-03 — структурный результат tool-loop
- Успех = `info["status"] == tool_result.STATUS_OK` из `_classify`
  (K1 ON → `classify_output`; OFF → legacy `_classify_output` — ТОЖЕ
  структурная деривация JSON-status/«ОШИБКА»-префикс, substring нет).
  `delivery_unknown`/empty/error/битый info → 0 (notice остаётся —
  «Не удалять уведомления о недоступности» соблюдено).
- JSON `status:"error"` и «ОШИБКА…» дают error/timeout/denied независимо от
  подстрок внутри (classify_output, tool_result.py:499-549) — substring
  `'"status": "success"'` внутри структурной ошибки успехом не считается.
- Call-site map base vs candidate идентичен: sync 2 (683→691, 1033→1042);
  третий `_classify` (870→878) — invalid-args путь ДО исполнения, синк там
  не нужен (и в базе отсутствовал) — не регресс.
- `record_outcome`/`notice_block` (синхронизация Capability Registry и
  Writer) не тронуты; прежние end-to-end контракты зелёные.

## Регрессия и запуски (кандидат 6ddc5351)

| Запуск | Результат |
|---|---|
| `py -3 -m compileall services` | rc=0 |
| `py -3 tools/gen_param_registry_round1025.py --check` | OK: 588 == REGISTRY |
| tests/test_asap5_image_admin.py (обновлён, COR-контракты) | 36 passed |
| tool_loop/router/calling/chains/mca11_tool_result/smoke_round1016 | 179 passed, 1 fail (pre-existing, см. ниже) |
| asap8_b04_edit_contract + vision_adapt + p0_vision_fix_core + postgen_diag + direct_chat | 341 passed |
| factcheck_media_2026_10_25 + asap5_w3 + post_asap5_w1/w2 + addtr | 186 passed |
| soul1_capability_intent/registry/fallbacks + mca19_block_b/c (vision) | 229 passed |

Base-сравнение: единственный сбой кандидата
`test_tool_chains_round1026.py::TestR17AndBoundaries::test_catalog_counts_unchanged`
(`assert 588 == 587`) воспроизведён 1:1 на чистой базе `563aac43`
(detached-прогон, 1 failed тем же ассертом) — pre-existing расхождение
release-линии с master-freeze тестом, кандидатом не вносится. Прочие
pre-existing из списка builder'а (env-PIL/ffmpeg/миграции/AST-freeze/flaky
node-spawn) в моих фокусных прогонах не проявились (меньше сбоев, чем
заявлено — не регресс).

## Находки

- BLOCKING: нет.
- MAP_SYNC_REQUIRED (PM/Orchestrator, clerical): bind-коммит → COR-01/02/03
  VERIFIED @ 6ddc5351, needs-real-env примечание COR-01 сохранить; текст
  acceptance в карте кандидатом не менялся (диф карты пуст — усечения нет).
- NONBLOCKING (backlog): детерминированного теста «reply на изображение +
  edit-фраза» нет; риск маршрута нулевой (edit-классификации в детекторе
  нет), L1-контекст reply подтверждён кодом. Инцидентальный note:
  результат edit сохраняется/отправляется с filename="image_edit.png"
  (tool_router ~:3702) — pre-existing вне скоупа COR-01 (тот — про исходник).

## Binding

Поведенческий вердикт привязан к артефакту `6ddc5351` (полный диф 7 файлов:
capability_registry, direct_capabilities, direct_chat_service, tool_loop,
tool_router, test_asap5_image_admin, evidence/cor-fixes.md) и прогонам в
worktree `adminbot-wt-pa5cor-rev`. Любое изменение кода/конфига этих путей
инвалидирует доказательства. SSH/прод/Telegram/LLM ревью не трогало.
