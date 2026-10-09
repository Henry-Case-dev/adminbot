# F6 — Cover content-loss fix (ASAP 7, Wave 2)

- Дата: 2026-10-09. База: master `e6670b0` (Wave 1). Коммитов нет (по регламенту).
- Контракт: architecture.md §2.1/§2.2/§2.3(гарантии)/§2.4; audit-cover.md B1/B2/B4/B5/B6; current_task.md §8/§11/§12/§22.
- Проверка: `py -m pytest tests/test_asap7_cover_fix.py` → 31 passed; фокус-соседи → зелёные (детали ниже). Полный pytest не гонялся (правило).

## 1. Изменения (file:line по текущему дереву)

### 1.1 Канонический порядок + B4 (§2.1)
- `services/cover_prompt_assembly.py:150-160` — `cover_prompt_order()` / `default_total_cap()`; env `SUMMARY_COVER_PROMPT_ORDER` (`story_first` default | `style_first` legacy), неизвестное значение → `story_first`.
- `services/cover_prompt_assembly.py:187-195` — **B4**: `style_cap = min(style_cap, max(0, total_cap - story_min))` в обоих режимах (миссконфиг style_cap>total больше не переполняет кап и не съедает story-minimum; sane-конфиг 500/1000/160 — байты прежние).
- `services/cover_prompt_assembly.py:277-310` — `base_prompt_plan` story_first-ветка: STORY_SCENE → SUMMARY_CONTEXT → BASE_STYLE; защищённые бюджеты: style floor 160 (`STYLE_FLOOR_CHARS:47`), story-minimum 160 (D8), ctx ≤400; story физически не выбрасывается целиком, пока cap ≥ story_min.
- `services/cover_prompt_assembly.py:323-332` — `compose_base_cover_prompt` = канонический сборщик (join по порядку плана). EDIT-компилятор `compile_style_prompt` (cover_style_jobs.py:1155) проверен: тот же resolved limit через `compiler.compile_prompt(capabilities=...)` — без изменений (§2.3 гарантия).

### 1.2 GENERATE prompt-limit + shorter-retry (§2.2)
- `services/image_generation.py:128-158` — `ImageGenerationError(provider_body=…)` (санитизированное тело 400 — только для серверной классификации) + `GenerationResult.meta` (enum/числа).
- `services/image_generation.py:844-860, 957-971` — POST/GET 400: тело (ключ вырезан) едет в исключение; лог не изменился (R17).
- `services/image_generation.py:1180-1210` — классификация в `generate()`: число → `prompt_limit` {value, unit} (machine-readable `extract_prompt_limit`), too-long без числа → `prompt_limit_unknown`, прочий 400 → `bad_request` (паритет EDIT/T-4875).
- `services/image_generation.py:665-711` — `resolve_generate_prompt_limit[_async]()` — единый резолвер `image_capabilities` c `operation=OPERATION_GENERATE` (manual override → discovery → registry → runtime-cache → unknown); `trim_prompt_to_limit()` — детерминированный word-boundary trim для standalone-маршрута.
- `services/image_generation.py:1290-1301, 1375-1470` — **shorter-retry**: после 400-too-long → РОВНО ОДИН повтор (max 2 платные попытки, бюджет списан 1 раз); callback `shorter_prompt(prompt, value, unit)` (обложка пересобирает Base компилятором: story+ctx сохранены, стиль сжат до floor) или trim-fallback; observed limit → `record_runtime_limit` (TTL-cache learning); повторный too-long → `prompt_limit_unknown_after_retry`; durable media job получает фактический (последний) промпт; `attempt_log` — in-process список попыток для манифеста.
- `services/summary_generator.py:2905-2950` — резолв лимита ДО компиляции: known → `compose_base_cover_prompt(..., total_cap=min(1000, limit_to_chars(N, unit)))` (tokens ×3 / bytes ÷2 — консервативно); unknown → компиляция под assembly-кап 1000 БЕЗ дополнительного silent trim + событие `COVER_LIMIT_UNKNOWN` (`cover_prompt_assembly.py:53`) + честный манифест `limit_source="assembly_cap"`, `resolved_limit=1000`.
- Манифест (§2.3 инвариант): `cover_prompt_assembly.py:579-633` — `build_base_manifest(..., resolved_limit/limit_unit/limit_source/attempts/component_reasons)`; после retry `limit_source="observed_provider_400"`, `resolved_limit=observed`, attempts=[retry_superseded, ok]; `final_prompt` == фактический последний request.prompt (== media job prompt). Полный prompt — ТОЛЬКО в task_jobs-манифесте, не в логах (R17).
- Оба маршрута покрыты: Summary Base Cover (compile+callback) и standalone generate (trim-retry) — тесты 12-16.

### 1.3 Anomaly guard §11 (§2.4)
- `services/cover_prompt_assembly.py:431-475` — чистая функция `cover_context_decision(cover_prompt, title, paragraphs)`: статья ≥ `MIN_MEANINGFUL_CHARS=80` (:50) и STORY пуст → `anomaly_recovered` (story=`derive_fallback_cover_prompt(article)`, ctx пересобран из финального документа; 0 LLM) / статья короче → `cover_context_missing`. Пометка: SUMMARY_CONTEXT ≡ f(document), поэтому пустой ctx при содержательной статье невыводим по построению — триггер по irreplaceable-компоненте (сцена), ctx при восстановлении пересобирается всегда.
- `services/summary_generator.py:2370-2400` (Hybrid-гейт) и `:2860-2886` (точка сборки Base, defensive) — применение решения: recovered → сцена восстановлена → rich+cover, в манифесте STORY_SCENE `reason="anomaly_recovered"`; missing → обложки НЕТ, `_degrade_without_cover(reason="cover_context_missing")` + `_publish_meta["reason"]`; событие `COVER_ANOMALY` (enum-only: status/reason_code/run_id/chat_id) через `emit_cover_event` → mca_events (без правок cover_style_jobs/agentic_events).

### 1.4 B5 ceiling bound
- `services/image_capabilities.py:619-670` — `record_runtime_safe_ceiling(..., only_raise=False)`: `only_raise=True` не даёт learned safe ceiling ракетиться вниз от длины сжатого retry-промпта; возвращает сохранённое значение; exact-источники по-прежнему сильнее.
- `services/cover_style_jobs.py:1977-1992` (только B5-регион, F8-зоны :1328/:2175 не тронуты) — передача `only_raise=True` + `ceiling_bound="only_raise"` в retry-диагностике.

### 1.5 B6 instruction + settings
- `services/summary_prompts.py:188-194` — `SUMMARY_EDITOR_COVER_PROMPT_BLOCK` дополнен требованием «Сцена обязана быть specific к этой выжимке… универсальные сцены запрещены». Лесенка миграций не тронута: прод-PG канон (hotfix4-текст) байт-в-байт равен `PREV_SUMMARY_EDITOR_R1025_HOTFIX4` → существующая ступень `(PREV_HOTFIX4 → SUMMARY_EDITOR_SYSTEM_PROMPT)` автоматически поднимает PG на новый канон (проверено тестами test_hotfix4 CoverCanon + prompt_migrations, кроме 3 F1-хвостов — см. §4).
- `config/settings.py:1120-1129` — **свой помеченный блок F6**: `SUMMARY_COVER_PROMPT_ORDER` (env-only ClassVar, Δ каталога = 0). F1-блоки не тронуты.

## 2. Тесты
- **Новый** `tests/test_asap7_cover_fix.py` (31 тест, TEST-LIFECYCLE: CONTRACT owner=asap7/F6 + REGRESSION B1/B2/B4/B5): ordering (3+floor+story-min), B4 (misconfig ×2 + legacy-байты), limit_to_chars, E2E A/B маркеры (§12: свой маркер в своём финальном промпте, чужой не протекает, known-limit укладывается, unknown-манифест честен), классификация 400 (3), shorter-retry (5: ровно-один/after_retry/standalone-trim/not-shorter/empty-builder), retry-компиляция сохраняет story+ctx (2), anomaly guard decision (3) + impl-интеграция (recovered → манифест reason + COVER_ANOMALY; missing → degrade cover_context_missing + 0 платных вызовов), known/unknown limit impl (4, включая retry-манифест observed_provider_400), B5 (3).
- Обновлены существующие тесты, защищавшие СТАРЫЙ байт-контракт (владелец изменил его §2.1; обновлены только позиционные assertion'ы, смыслы T-2509/T-2512/D8 сохранены): `test_asap5_cover_prompt_manifest.py` (story-min статусы + legacy-parity под style_first), `test_hotfix4_cover_nav_shell_round1025.py` (3 позиционных), `test_hotfix3_summary_fallback_round1025.py` (2), `test_summary_cover_round1023.py` (1 позиционный + build_cover_media-стаб как в общих хелперах), `tests/summary_cover_helpers.py`/`test_summary_cover_round1023.py`/`test_mca17_summary_instrumentation.py` — сигнатура мока `generate_image_verbose` принимает новые kwargs (`shorter_prompt`/`attempt_log`).

## 3. Результаты прогонов (фокус, без полного pytest)
- `tests/test_asap7_cover_fix.py` — **31 passed**.
- Соседи (cover/summary, grep-набор): asap5_cover_prompt_manifest, asap7_cover_readpath, asap44_cover_final_closure, model_compat_r1024, summary_cover_r1023, hotfix3, hotfix4, summary_two_call, verbilizer, target_marking, mca17, hotfix5_window, asap43, asap5_cover_manifest_web, cover_styles_contract, summary_prompts, summary_generator, cover_style_wave_f, extra_cover_style_jobs/pipeline/api, cover_style_wave_b, l2_integration, execution_graph, inspector_zone_g, deploy_r1026 и др. — **зелёные** (финальный сводный прогон: 338 passed в 12-файловом наборе + 154 + 298 в расширенных).
- py_compile всех затронутых файлов — OK.
- RED-факты до фикса (воспроизведены тестами на старом поведении): ordering story-first отсутствовал; B4 переполнение; 400-too-long классифицировался как generic `bad_request` без retry; guard отсутствовал (0 вхождений cover_context_missing).

## 4. Incidental findings
- **F1-seam (current-blocker для F1, не моего лейна)**: `tests/test_prompt_migrations.py` — 3 FAIL в общем дереве (`test_all_expected_keys_present`, `test_catalog_points_to_new_canons`, `test_missing_keys_skipped_info`): PROMPT_MIGRATIONS получил `prompts.direct_l1_planner_system_prompt` из параллельной правки F1 `services/prompt_migrations.py`. На HEAD-чек-ауте эти тесты зелёные (проверено в отдельном worktree). F1 обязан обновить ожидания `tests/test_prompt_migrations.py`.
- **Pre-existing (HEAD, вне лейна)**: `tests/test_summary_publish_integration_round1026.py::TestOnDelivery::test_on_l1_not_usable_level2_l2_publishes_article` — RED и на чистом HEAD (-worktree проверка); env-зависимый.
- **Pre-existing env**: в этом окружении aiogram без `InputRichMessageMedia` → реальный `build_cover_media` кидает ImportError; тесты, идущие через общий хелпер, стабят его; `test_summary_cover_round1023` теперь тоже (минимальный стаб добавлен, до этого файл был RED даже на HEAD — подтверждено worktree).
- Мелочь: дублирование derive-сцены в story при фолбэке hotfix3-теста («одиночный дерзкий текст» дважды) — pre-existing композиция (derive от title+text), не менял.

## 5. Как проверяется на проде после деплоя (observed-400 learning)
1. `GET /healthz` — 200/версия (живость; SSH не трогаем).
2. Run Inspector (F8 read-path, global admin): `GET /api/analytics/pipeline/runs/{run_id}?include_prompt=true` → `cover_base` манифест:
   - порядок компонентов: STORY_SCENE → SUMMARY_CONTEXT → BASE_STYLE (маркер summary в начале final_prompt — гипотеза style-only закрыта владельцем по §12 A/B: два разных summary → разные финальные промпты);
   - `limit_source`: `assembly_cap` (unknown) | `manual_override`/`provider_or_registry`/`cached_runtime_discovered` (known) | **`observed_provider_400`** — после первого реального 400 too-long: это и есть runtime-подтверждение капа провайдера (source observed, без paid-проб); attempts[0].outcome=`retry_superseded`, attempts[1].outcome=`ok`;
   - STORY_SCENE.reason=`anomaly_recovered` — сработал §11-guard (сцена выведена из статьи).
3. mca_events: `COVER_ANOMALY` (status=anomaly_recovered | cover_context_missing), `COVER_LIMIT_UNKNOWN`, `COVER_BASE_FAILED` reason_code — grep-able, enum-only.
4. Откат: `SUMMARY_COVER_PROMPT_ORDER=style_first` → прежний порядок байт-в-байт (тест: compose == legacy compose_cover_image_prompt); правка манифестов/лимитов аддитивна.

## 6. Остаточный риск
- units tokens/bytes конвертируются консервативно (×3 chars/token, ÷2 bytes/char) — промпт может быть короче физически возможного; не опасно (худший случай — не используем весь лимит).
- Патологические капы (total < ~320) → деградация с честными status/omitted; story-min > cap невозможен по построению (clamped к cap).
- DIRECT-чат tool path: короткий ретрай только по факту 400-too-long (pre-send trim для tool-промптов сознательно не вводился — паритет поведения).

## REWORK B11 (REV-2, Medium — бюджет ≤2 платных вызова нарушался)

- Дата: 2026-10-09. Лейн F6-REWORK,_writer-only по blocking finding REV-2 B11.
- Дефект: инвариант «≤2 платных вызова на обложку» (§2.2.4, докстринг generate_image_verbose) нарушался в достижимой цепочке: попытка 1 — transient (timeout/network/429 — каждая итерация цикла = отдельный платный вызов), попытка 2 — 400 too-long → shorter-retry = ТРЕТИЙ платный вызов (при env max_attempts=5 — до 6). Репро: paid_calls=3, reason=ok.
- Фикс: `services/image_generation.py:1442-1452` — shorter-retry разрешён ТОЛЬКО при too-long на ПЕРВОЙ платной попытке (`attempt < 2` на входе в блок; attempt после выхода из цикла == число платных вызовов). Иначе — честный терминальный исход существующим failure-путём (finish_media_job MJ_FAILED + fallback §31), без retry. Прямой 400-путь не сломан: 400 на попытке 1 → 1 shorter-retry = 2 суммарно; unknown → без trim (без изменений); attempt_log/reason-семантика прежние.
- Тесты (`tests/test_asap7_cover_fix.py`, TestShorterRetry, +4 инстанса, REGRESSION owner=REV-2/B11):
  - `test_transient_then_400_no_shorter_retry_budget` (param max_attempts=2,5): timeout→400 too-long → ровно 2 платных вызова, честный терминальный `prompt_limit`, attempt_log пуст (ретрай не начинался), resend-промпт не менялся;
  - `test_400_on_first_attempt_retry_within_budget` (param max_attempts=2,5): 400 на первой попытке → retry → ok = ровно 2 платных вызова при любом env max_attempts (env>2 бюджет не расширяет).
- Прогоны: `py -m py_compile` (оба файла) — OK; `tests/test_asap7_cover_fix.py` → **35 passed** (31 прежних зелёные + 4 новых; точечно -k: 4 passed); соседи image/cover-grep: asap44_cover_final_closure + asap42_step2c2/step3 + asap43 → 58 passed; asap5_cover_prompt_manifest + asap7_cover_readpath + hotfix5_window_round1025 + summary_cover_round1023 + mca17 + media_execution_asap32 → 128 passed. Коммитов нет.
- Подтверждение бюджета: любая цепочка с shorter-retry суммарно ≤2 платных вызова (transient-попытки цикла считаются — каждая отдельный платный запрос; собственный transient-бюджет цикла Хотфикс-5 (env max_attempts) не входит в лейн B11 и не менялся).
