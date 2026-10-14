# ASAP 8 Phase B — Architecture (F1–F10)

Baseline: master `0c4f3a5` (2.58.74). Входы: ТЗ ASAP 8 (`plans/current_task.md` §0–§31), аудиты Phase A
(`audit-summary.md`, `audit-cover.md`, `audit-modules-infra.md`), `plans/runtime_task.md`.
Принцип: чинить существующий контур, не переписывать; §28-запреты и §0 owner-contracts — жёсткие.
ΔDDL: **нулевой** — все решения укладываются в существующие таблицы (`mca_intents`, `mca_events`,
`task_jobs`, hot-настройки). Секреты: proxy/embeddings панели без credential-значений.

---

## 1. F1 — Summary L2 validator reliability + granular diagnostics

### 1.1. Порядок repair → correction (решение развилки)

**repair-first, correction-second.** Deterministic repair всегда бесплатен → выполняется первым;
LLM-correction (дорого) — только против post-repair остатка. Обратный порядок тратил бы вызов LLM
на дефекты, которые детерминированный код чинит.

Пайплайн `run_l2` (единственный владелец, `summary_l2_writer.py`):

```text
attempt 1 (LLM) -> parse -> _validate-канонизация
  внутри цикла канонизации: granular detect -> deterministic repair -> revalidate (один проход)
если после repair документ невалиден И дефект CORRECTIONABLE:
  ровно ОДИН correction attempt (machine reason в user-контент) -> validate
если снова невалиден -> L2Result{usable=False, reason=<granular>} -> Legacy (как сейчас, :2298-2325)
```

### 1.2. Классификация дефектов (reason-модель, аддитивная — §28.1)

`reason` = гранулярный код, `reason_group` = старый umbrella (обратная совместимость аналитики).

| code | group | deterministic repair | correctionable |
|---|---|---|---|
| `paragraph_bad_type` (не-str элемент) | invalid_paragraph | нет | да |
| `paragraph_empty` | invalid_paragraph | удалить только пустой элемент | да (если document_no_paragraphs) |
| `paragraph_too_long` (>900) | invalid_paragraph | split по sentence boundary, весь текст сохраняется, evidence refs следуют за предложением, emphasis пересчитан штатным нормализатором | да (одиночное предложение >900) |
| `paragraph_empty_after_cleanup` (ID-strip) | invalid_paragraph | удалить non-content элемент | да (если всё опустело) |
| `document_no_paragraphs` (/:1046-1047) | invalid_paragraph | нет | да |
| `invalid_evidence` (invented, :950-958) | invalid_evidence | НЕТ (S3: fail-closed вне anchor-ремонта) | да |
| `quote_attribution` (:1006-1022) | quote_attribution | НЕТ (wrong-person не ремонтируем) | да |
| JSON parse fail | structural | НЕТ (structurally broken — §2.3 запрет) | да |

Telemetry: `SUMMARY_L2_STAGE` (pipeline_events.py:294-306) + WARN `L2_ERROR` получают
`reason_code`, `paragraph_index`, `chars` (текст абзаца — никогда). Поля `l2_calls` (1|2),
`correction_used`, `repair_actions[]`.

### 1.3. Контракт изменения инварианта вызовов

Docstring/инвариант `summary_l2_writer.py:11-14` меняется ЯВНО: happy path = 1 вызов L2;
максимум = 2 (attempt + correction); бюджет ≤5 генераций на run не трогается (L1+L2+correction ≤3).

### 1.4. Размещение

Новый чистый модуль **`services/summary_l2_repair.py`** (без LLM, без I/O):
`detect_paragraph_defects(doc, package) -> [Defect{code,index,chars}]`,
`repair_document(doc, package) -> (doc', actions)`. Вызывается из цикла канонизации `_validate`
(точки вставки: до `_reject` :934-943, :1046-1047) — writer остаётся владельцем валидации,
repair-модуль легко тестируется отдельно. Correction attempt — внутри `run_l2` (:1409-1424
расширяется до attempt+correction), `summary_generator.py` меняется только pass-through reason.

### 1.5. UI truth: attempted_invalid + coverage-оси

- `_durable_stage_result` (summary_generator.py:2274-2278): validator-invalid → **`attempted_invalid`**
  (семантика: стадия выполнена, вывод отвергнут детерминированным валидатором, включён fallback);
  `failed` остаётся только для transport/структурного провала без пригодного вывода.
- `SUMMARY_L2_STAGE outcome=attempted_invalid, reason_code`; `web/app.js:3529-3534`:
  `attempted_invalid: 'выполнено, отвергнуто валидатором'` (+ reason-code человекочитаемо).
- Coverage headline (Summary Inspector) — четыре раздельные строки, поля уже есть в
  `_coverage_breakdown` (pipeline_analytics.py:724-850, UI :3444-3516):
  `Source ingested / L1 semantic / L2 accepted (новая строка: hybrid-принятые документы) /
  Final`. Единый скаляр `usage.coverage` из headline убирается; `health_of` (:1197-1205)
  деградирует по final-оси как раньше. Legacy-overwrite (:1323-1355) остаётся, но влияет
  только на Final-ось.

### 1.6. Golden-тесты L2

Аддитивные поля + `reason_group` сохраняют большинство золотов. Тесты, пинящие точный
`invalid_paragraph` на repairable-дефектах (пустой/950-char абзац), обновляются намеренно —
они закрепляли дефект (тип §18.1 self-fulfilling). Остальное множество не трогается.

Тесты: S1, S2, S3, S4. Риск: R1 (изменение валидатора — прикрыто негативными регрессами S3/§2.3).

---

## 2. F2 — Unified Summary execution input (Test = production, §0)

### 2.1. Контракт

Новый модуль **`services/summary_execution_input.py`** (не метод generator'а: три call-site'а,
включая test-harness, который не должен тянуть generator):

```python
@dataclass(frozen=True)
class SummaryExecutionInput:
    rows: list; source_window; anchor_map
    budget_l1; budget_l2; focus_block; length; slot_l1; slot_l2
    fingerprint: str   # от run_id + checksum(rows) — детерминирован

def build_summary_execution_input(*, chat_id, rows, correlation_id,
                                  focus=None, trigger_message_id=None,
                                  window_run_id=None) -> SummaryExecutionInput
```

- prod: `summary_generator.py` — `_establish_source_window`/`_run_hybrid_l2` (:647-650, :704-750)
  и вызовы `run_l1(..., source_window, focus_block)` (:1931-1935) / L2 (:2168-2172) берут поля из
  ExecutionInput; durable-окно как сейчас.
- test: `summary_test_run.py:520-559` — вместо `build_test_rows` + голого `run_l1`;
  окно **in-memory** (`build_source_window` с test run_id, 0 durable-записей — fingerprint
  строится от run_id+rows, валидно), `run_l1(..., source_window=inp.source_window,
  focus_block=inp.focus_block)`, L2 с `source_input/anchor_map/length` (:630-652).
- replay/debug: через `source_window_from_row` (summary_source_window.py:193-216).

Инвариант: один fixture → одинаковые source-window fingerprint и anchor_mode в prod/test (S5).
§28.3: отдельного preparation path у теста больше нет.

### 2.2. map-v1 unknown-ref repair (путь dry-run, §3.4)

`validate_semantic_map` (summary_l1_semantic_map.py:294-428) сегодня fail-closed на первом
unknown id. Добавить deterministic remover по образцу `summary_l1_repair.py`: небольшой мусор →
удалить; `map_useful_after_repair` → продолжить; useless → существующий РОВНО ОДИН correction
retry (clusterizer:2101-2135) → fail-closed. Invented refs никогда не резолвятся (§28.4).
Telemetry §3.4 (`unknown_refs_count`, `removed_unknown_refs`, `map_useful_after_repair`,
`retry_used`, `anchor_mode`, `source_window_present`) → `RepairReport.as_log_fields`
(summary_l1_repair.py:83-86) + counts в `SUMMARY_L1_STAGE`.

Тесты: S5, S6, S7. Зависимость: BLOCKED_BY F1 (общие файлы summary_l2_writer/summary_generator).

---

## 3. F3 — Style Edit scene preservation

### 3.1. Новый порядок приоритетов `compile_style_prompt` (cover_style_jobs.py:1155-1238)

```text
P0 CONTENT_PRESERVATION_INVARIANTS   (новый компонент, первый в строке, в required-ядре
                                      и в retry_core-ядре — никогда не режется)
P0 ISSUE/TEXT INVARIANTS             (runtime_invariants_text, как сейчас)
P1 STORY_IDENTITY                    (story_scene + brief.render() — поднят из «budget_component»
                                      в P1, story floor 160 сохраняется)
P1 STYLE_IDENTITY minimum            (profile.instruction, identity floor ≥50% как сейчас)
P2 REFERENCE_DESCRIPTIONS
P2 base_style_prompt                 (ПОНИЖЕН с P1)
P3 decorative extras
```

Preservation-блок — формулировка §5.3 ТЗ (Builder может адаптировать слова, смысл нельзя):

```text
Preserve the exact depicted event, people, actions, object relationships,
composition and framing from the input image.
Do not replace the scene with a generic portrait or generic city scene.
Apply the requested visual style without changing the story content.
```

Порядок строки в компиляторе: preservation → issue → story → style_instruction → refs →
base_style → decorative. Базовая механика `image_prompt_compiler.compile_prompt` (P-уровни как
данные, required=P0+P1) НЕ меняется — EXTRA-контракты (priority-aware compilation) целы.

### 3.2. Судьба base_style_prompt

**Понизить до P2, не удалять.** Его эффект уже запечён в input image (audit-cover §2), поэтому
как неурезаемый P1 он доминирует сюжет; но текст нужен preview-ветке и snapshot-OFF
(cover_style_preview.py:440), поэтому полное удаление ломает честный предпросмотр. P2 = едет при
отсутствии давления, падает первым при давлении.

### 3.3. Fail-soft (§5.4): детекция «не способен сохранить content» — по контракту промпта

Сигнал детерминированный, из результата компиляции (не LLM-судждение):
`cover_brief dropped` ИЛИ story floor не влез ИЛИ P0-overflow (`prompt_limit_exceeded`)
⇒ styled НЕ публикуется, публикуется Base; manifest помечает
`style_publish_skipped{reason: story_identity_dropped | prompt_limit_exceeded}`.
Точка хука — существующий fallback на overflow (cover_style_jobs.py:1794-1809), П0-механика
выпуска не меняется. `dropped[]` больше не «виден только в манифесте» — он меняет исход публикации.

Тесты: C1 (не регрессировать), C2, C4. Зависимости: нет (SERIALIZE перед F4).

---

## 4. F4 — Exact prompt UX (C5/C6/C7)

### 4.1. Latest-mode auto-load (решение: server-side resolve)

`GET /api/analytics/pipeline/runs/latest?include_prompt=true` (global-admin, fail-closed 403 как
сейчас web/api/analytics.py:630-670): сервер резолвит latest run_id той же сортировкой, что
список инспектора, возвращает detail + cover_prompts + cover_prompts_status. Клиент
(`web/app.js::loadPipelineInspector` :5523-5551, `setPipelineMode` :5552-5557): в режиме
«Последний запуск» (пустой `pipelineSelectedRunId`) и при начальной загрузке — прямой вызов
latest-endpoint. Никакого скрытого extra-click (§28.7).

### 4.2. Missing manifest → явная причина (решение: backend reason)

`load_run_cover_prompts` (cover_style_jobs.py:1328-1376) возвращает, помимо манифестов,
`cover_prompts_status: {base: <code>, style: <code>}`:

```text
ok | base_manifest_missing | style_job_not_linked | style_job_failed | legacy_run
```

UI: блок «Фактический промпт» для global admin виден ВСЕГДА (`pipelineCoverPromptsVisible`
:3679-3683 больше не гаснет по отсутствию манифестов); при missing —
«Фактический промпт недоступен · reason» (§28.8). `legacy_run` = нет coalesce-ключа и нет
job-записи эпохи манифестов.

### 4.3. Preview-compile v2 (страница «ИИ → Промпты → Стиль обложки»)

Расширение существующего `POST /api/cover/preview-compile` (cover_styles.py:1463-1592):
body получает `mode: "base"|"style"` (default `base` — полная обратная совместимость).
`mode="style"` компилирует `compile_style_prompt` (runtime invariants + preservation + draft как
base_style + refs + issue_display + опциональный story/context source). Context: `{chat_id}`
опционально — endpoint уже global-admin fail-closed, произвольный чат разрешён в этой поверхности;
контекста нет → честно «контекст недоступен» + reserved budget (паттерн placeholder :1539-1566).
Ответ: style source, story/context source, model/route/limit, exact compiled prompt, chars/limit,
sent/trimmed/omitted. **JS-дубликата компилятора нет** (§28.9, C7). Переиспользуются лимит-резолвер
и budget (:1500-1537).

Тесты: C5, C6, C7 + дополнить `tests/js/asap7_f8_cover_prompts_test.js` latest-режимом (§18.2:
пустой selection → ожидаем вызов include_prompt). Зависимость: BLOCKED_BY F3 (контракт манифеста
и preserve-компонент).

---

## 5. F5 — Module dependency truth (главная развилка)

### 5.1. Решение: (а) роутеры инклюдятся ВСЕГДА + внутренние runtime-гейты

Проверка кода: `bot.py:840-874` инклюдит роутеры 0a–0i только при startup-значении
`flags.summary_enabled`; в `handlers/` НЕТ ни одного runtime-чтения `flags.summary_enabled`.
При этом собственные runtime-гейты УЖЕ есть у factcheck (`factcheck.py:384
flags.factcheck_enabled`), search (`:119`), web (`:143`), checkup (`:97`), youtube-video
(`youtube.py:1355 flags.video_summary_enabled`). Не хватает runtime-гейтов:

- `summary_observer_router` + `summary_router` → добавить проверку `flags.summary_enabled`
  на входе хендлеров (per-chat allowlist уже есть, summary.py:517-521);
- `voice_transcription` → добавить проверку `flags.enable_voice_transcription`
  (AND-гейт из bot.py:873 переезжает в рантайм; `summary_enabled` из него УДАЛЯЕТСЯ);
- `direct_chat` → master-гейт `flags.direct_chat_botword_enabled` на reply/mention-пути
  (сегодня флаг читается только keyword-веткой :194-197).

Вариант (б) «отдельно названный bootstrap-master» отклонён как основной: он не убирает ложь
«Включён, но не работает» после toggle-off и оставляет мёртвые модули при env-off. Restart-семантика
сохраняется честно: UI-причина `env_off`/глобальный toggle действует в рантайме; инклюд-обёртки
снимаются, ПОРЯДОК РЕГИСТРАЦИИ (bot.py:836 «CRITICAL») не меняется — только `if`-обёртки.

### 5.2. Reason-модель UI (замена parentGate)

`parentGate: 'flags.summary_enabled'` удаляется у 7 модулей (app.js:556-595); все модули из ТЗ
§11.3 — independent. `_moduleRuntimeState()`/`moduleRuntimeNotice()` (:9166-9220) различают:

```text
chat_off               — «выключено в этом чате»
global_off             — «выключено глобально» (ТОЛЬКО когда selected scope = global)
env_off                — «аварийный env-переключатель выключен»
provider_unavailable   — «провайдер/возможность недоступна»
parent_off             — реальная parent-зависимость (зарезервировано; сейчас не используется)
```

§28.10 закрыт; M1–M3 тестируются на ложный «отключён глобально» при chat scope.

### 5.3. Random: product master (решение по логике §10)

`Случайность` имеет продуктовые настройки (вероятности, memory.random_uses_*), которые владелец
разумно захочет включать/выключать без SSH ⇒ это логический модуль ⇒ в каталог добавляется
product master `memory.random_enabled` (default true, категория memory, группа Random);
`module_registry.py:172-194` получает `master_param`; env `MCA_RANDOM_SOURCE_ENABLED` остаётся
аварийным AND-гейтом. Промежуточный вариант не существует по определению. Пин
`tests/test_asap7_module_completeness.py:225-226` обновляется вместе с мастером (§18.1).

### 5.4. Experience: worker global + per-chat opted-in check (решение по логике §9)

Каталог исторически per-chat (param_catalog.py:2327-2343) — это продуктовое намерение, меняем
runtime/registry под него, а не каталог: `_learning_enabled()` (mca_experience_jobs.py:118-130)
получает chat-resolver (hot per-chat override → global → default) и глобальный worker
(memory_maintenance.py:229-242) обрабатывает только opted-in чаты. `module_registry`/UI-текст:
«worker глобальный, обучение по чатам» — catalog/registry/runtime согласованы (M6). DDL нет.

Тесты: M1–M3, M6, M7 (+ обновлённый completeness-тест). Параллельность: F5 блокирует F7
(общие module_registry/catalog/app.js).

---

## 6. F6 — Initiative v2: producer → decision → L2 → send

### 6.1. Producers (минимальный реальный набор; репо-факт: create_intent call-sites в prod = 0)

Детерминированные точки привязки, никакого LLM-письма в DB и никаких intent на каждое сообщение:

| producer | событие-привязка | kind / origin |
|---|---|---|
| unanswered_question | конец Direct-хода: пользовательское сообщение с '?' и бот не отправил reply в этом ходе | `follow_up` / `unanswered_question` |
| explicit_request / future intent | Direct L1/Coordinator возвращают allowlisted-поле future-intent (парсер L1 валидирует схему, сервис пишет intent — LLM в DB не пишет) | `follow_up`/`open_dispute` / `explicit_request` |
| search_result | завершение async search/tool job с результатом, не потреблённым ответом | `topic_interest` / `search_result` |

Guard-ы: dedup по (chat, origin, subject) в окне; cap pending intents на чат; порог качества до
funnel-evidence не ослаблять (§28.16). `unfinished_topic`/`answer_extension` отложены до
детерминированного сигнала — не спамить.

### 6.2. Consumer: убить вечный candidate_ready

Due candidate → compact context (intent + свежее окно чата + relevant memory + personality/self-model)
→ initiative decision (существующая L1-модель: REPLY/REACT/SILENT). REPLY ⇒ **существующий** Direct
L2 Writer `trigger=initiative` → `prepared_text` → существующий SendRecheck
(mca_intents.py:520-562, подключён direct_chat_service.py:7361-7379) → отправка существующими
chunks/ledger (:7373-7409). Третьего Writer нет (§13.2). Генерация происходит В heartbeat-пути
(memory_maintenance.py:244-283 → handle_initiative с prepared_text-генерацией); неспособность
сгенерировать → intent в терминальное `writer_failed` (bounded attempts), не бесконечный defer
(§28.15). Защита цепочки `chain_allowed` (mca_intents.py:650-654) не трогается.

### 6.3. Funnel-статус (status_service.intent_snapshot :741-856)

Поля: `heartbeat_registered/last_heartbeat`, `producers_24h` (по origins), `intents_created_24h`,
`pending`, `due`, `decisions_24h`, `writer_generated_24h` (новое событие при L2-генерации
trigger=initiative), `recheck_passed`, `sent` (ledger output_kind=initiative), `last_skip`,
`top_block_reason`. Формула вместо «не запускалось» — четыре диагностических состояния из
audit-modules-infra §11 (producers=0 → «Heartbeat работает, producers за 24ч не создали ни одного
намерения» и т.д.; §28.14, I8). Данные: `mca_events` уже пишет intent_created/decided/recheck_deferred
(status_service.py:802-846) — добавляются только счётчики writer_generated/sent.

Тесты: I1–I9. Параллельность: PARALLEL_SAFE (не пересекается с summary/cover; status_service —
его зона). Риск: R2 (живая инициатива — DoD требует live proof).

---

## 7. F7 — Stories humanize (+ Random/Experience решены в F5)

- Карточка эпизода: дата, короткое название/суть, display names (резолв канон-ID через
  IdentityResolver/aliases — серверно), source message count, «использовалась ли потом».
- Лента/управление: `Участники (ID)` (index.html:2529, :7010-7011) → display names;
  `episode_id`/raw IDs/build internals → под Developer details (collapsed).
- Заголовок/подпись: человеческое объяснение §14 («Истории памяти — связанные куски разговора…»,
  НЕ Telegram Stories, НЕ Summary). Данные уже есть в /api/stories/* (stories.py:92-146) —
  контракт: `display_names` добавляется в feed/card ответы. Витрина «Всего/Новых за 24ч/Последняя
  сборка/Backfill» — как в ТЗ. §28.17 закрыт.
- Random/Experience — контракты в §5.3/§5.4 (реализуются этим же слайсом в UI-части).
- Stories humanize (данные есть). Тесты: M4, M6, M7 UI-часть. Зависимость: BLOCKED_BY F5.

---

## 8. F8 — Embeddings quota groups (UI существует: memory_agi.py:484-522)

Добавить в панель (без secrets):
- per-credential: alias, provider/model, quota group; per-group: health (ok/cooling/exhausted),
  `cooldown_until`, last 429;
- honest rotation semantics: «rotation=none · все N ключей в одной группе unknown» WARN-баннер +
  hint конфигурации `keys.embedding_quota_group_labels` (источник :267-269, hint :308-309) —
  закрытие §28.18/§28.19/E1; не считать разные ключи независимыми квотами без evidence.
- WARN-спам: опровергнут аудитом (1/batch, summary_memory.py:3064-3081) — НЕ трогать (E5 уже ок).
- Backfill: `_ensure_vec_retry` (:2147-2190) триггерится только read-path ⇒ добавить периодический
  re-probe в существующий maintenance tick (покрытие случая «нет read-трафика»); при runtime-
  добавлении labels — пересбор registry групп (unknown-group случай: после конфигурации пул
  размораживается, backlog уходит в backfill). Прогресс backlog — INFO + счётчик в панель.

Тесты: E1–E5 (E2/E3 на разделение групп). Параллельность: PARALLEL_SAFE.

---

## 9. F9 — YouTube proxy classification + health

`_is_transient` (youtube_transcript_engine.py:527-574) — сначала специфичный парс, потом класс:

```text
407 / "Proxy Authentication Required" (в т.ч. yt-dlp DownloadError "HTTP Error 407" —
  парсить ДО generic "http error"-чека :567-568)  => proxy_auth_failed, permanent, no retry, WARN 1/request
403                                              => forbidden (per-request), no exponential retry
429                                              => transient (backoff как сейчас)
timeout / reset / proxy unavailable / ProxyError(не 407) => transient bounded (4 попытки)
```

Retry-матрица фиксируется таблицей в модуле; Y1–Y3. Единый effective proxy profile для yt-dlp и
transcript-api (общий хелпер классификации + один профиль) — проверяется тестом Y4. Proxy health:
MiniApp-блок + connection-test endpoint (global-admin): proxy configured (host:port маскирован),
auth OK/FAIL, результат yt-dlp path, результат transcript-api path, last_check; secrets никогда
(Y5). Direct/no-proxy fallback — только за явной owner-настройкой (default: fallback нет, как
сейчас; включение логируется). §28.20/§28.21 закрыты. Параллельность: PARALLEL_SAFE.

---

## 10. F10 — plans/status/help reconciliation

- `plans/features/asap7-cognitive-direct-pipeline` → `plans/archive/asap7-cognitive-direct-pipeline-round1049/`
  (прецедент f0, содержимое сохранить); runtime_task/workflow_state синхронизированы с HEAD
  (Phase A уже сделала, закоммитить); current_task.md остаётся owner-owned вне master.
- Truthful Status (§17) — финальная семантика всех 6 статусов: `attempted_invalid` (F1),
  4 coverage-оси (F1), module reason enum chat_off/global_off/env_off/provider_unavailable (F5),
  Initiative funnel-формула (F6), Embeddings rotation/cooldown честно (F8), Cover style:
  published / skipped_base_fallback{reason} + story-identity сигнал в манифесте (F3) —
  «style success» без сохранения сцены невозможен (§28.6).
- Help проверяется против нового runtime (F5-карта, proxy health, Stories): Help не обещает
  невёрифицированное (§28.23).
- §18-пины: completeness:225 (обновлён в F5), f8 JS latest-кейс (добавлен в F4).

---

## 11. Таблица F1–F10: файлы / тесты / зависимости / порядок

| Slice | Ключевые файлы (точки — из аудитов) | Тесты | Зависимость | Параллельность |
|---|---|---|---|---|
| F1 | summary_l2_writer.py (:78,:790-796,:925-1047,:1409-1424), **новый** summary_l2_repair.py, summary_generator.py (:2263-2325), pipeline_events.py (:294-306), pipeline_analytics.py (:1291,:724-850), app.js (:3529-3534,:3444-3516), index.html:4688 | S1-S4 | — | SERIALIZE (spine) |
| F2 | **новый** summary_execution_input.py, summary_generator.py (:647-750,:1931-1935,:2168-2172), summary_test_run.py (:520-652), summary_l1_semantic_map.py (:294-428), summary_l1_repair.py, summary_l1_clusterizer.py (:1968-2135) | S5-S7 | BLOCKED_BY F1 | SERIALIZE |
| F3 | cover_style_jobs.py (:1155-1238,:1794-1809), image_prompt_compiler.py (P-уровни как данные), cover_prompt_assembly.py | C2, C4, C1-регресс | — | SERIALIZE |
| F4 | cover_style_jobs.py (:1328-1376), web/api/analytics.py (:630-670), web/api/cover_styles.py (:1463-1592), app.js (:5523-5557,:3671-3683), index.html (:4632-4643, Промпты :2045-2110), tests/js/asap7_f8 | C5-C7 | BLOCKED_BY F3 | SERIALIZE |
| F5 | bot.py (:836-874), handlers/summary.py, voice_transcription.py, direct_chat.py, app.js (:544-595,:9166-9220), param_catalog.py, module_registry.py (:172-194) | M1-M3, M6, M7, completeness-update | — | BLOCKS F7 |
| F6 | direct_chat_service.py (:7242-7409), mca_intents.py, memory_maintenance.py (:244-283), status_service.py (:741-856), L1-parser (allowlist-поле) | I1-I9 | — | PARALLEL_SAFE |
| F7 | web/api/stories.py (:92-146), app.js, index.html (:2474,:2529,:7010), registry/catalog UI-тексты | M4, M6/M7 UI | BLOCKED_BY F5 | SERIALIZE |
| F8 | embedding_control_plane.py, summary_memory.py (:2147-2251,:3064-3081), memory_agi.py (:484-522), index.html (:4933-4944), memory_maintenance (probe) | E1-E5 | — | PARALLEL_SAFE |
| F9 | youtube_transcript_engine.py (:52-574), новый proxy-health endpoint, app.js/index.html (YouTube-панель) | Y1-Y5 | — | PARALLEL_SAFE |
| F10 | plans/*, Help-файлы, отчёт §30 | — | BLOCKED_BY F1-F9 | финал |

Порядок: spine F1→F2→F3→F4→F5→F7→F10 (§31 последовательно); лейны F6, F8, F9 могут идти
параллельно после F1 (write-scope не пересекается: direct_chat/intents/status vs embeddings vs
youtube). Каждый deploy wave — один-два слайса, prod evidence до закрытия.

## 12. Риски

- R1 F1/F2: валидатор и паритет — самые опасные регрессии; прикрыто S1-S7 + явное обновление
  инварианта «1 вызов» (§1.3) и golden-контракта (§1.6).
- R2 F6: живая инициатива — DoD owner gate; funnel до tuning thresholds (§28.16).
- R3 F5: порядок роутеров в bot.py — менять только обёртки; негативный тест на порядок регистрации.
- R0 F8/F9: локальные, покрыты E/Y-матрицами.
