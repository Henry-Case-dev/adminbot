# F2 — Unified Summary execution input (Test = production) + map-v1 unknown-ref repair

Baseline: master `d204ccb` (2.58.75, F1 закоммичен). Статус: реализация в рабочем дереве,
НЕ закоммичена (коммит после Reviewer). Зависимость F1 — выполнена.

---

## 1. Контракт SummaryExecutionInput

Новый модуль **`services/summary_execution_input.py`** (НЕ метод генератора: три call-site'а,
test-harness не тянет `summary_generator`):

```python
@dataclasses.dataclass(frozen=True)
class SummaryExecutionInput:
    rows: list
    source_window        # SummarySourceWindow | None
    anchor_map           # SourceAnchorMap | None
    budget_l1            # (kind, limit, budget_mode) | None
    budget_l2            # (kind, limit, budget_mode) | None
    focus_block: str
    length: dict | None
    slot_l1              # L1Slot | None
    slot_l2              # L2Slot | None
    fingerprint: str     # sha256(run_id ∥ messages_json)[:16]; "" — окна нет

async def build_summary_execution_input(*, chat_id, rows, correlation_id,
                                        focus=None, trigger_message_id=None,
                                        window_run_id=None,
                                        source_window=None,
                                        mount_window=False) -> SummaryExecutionInput
```

Отклонения от сигнатуры архитектуры (§2.1) — минимальные, задокументированы:

1. **`async def`** — резолверы бюджета/длины (`resolve_l1_effective_budget`,
   `resolve_l2_package_budget`, `_hybrid_length_for_chat`) асинхронны; синхронной
   сборки не существует.
2. **`source_window=` (готовое окно) и `mount_window=True` (in-memory mount)** — два
   способа получения окна в ОДНОЙ функции: prod передаёт durable-окно от
   `_establish_source_window` (постоянное хранение окна не тронуто); dry-run
   монтирует окно в памяти (`build_source_window`, **0 durable-записей**);
   replay/debug — `source_window=source_window_from_row(row)` (проверено тестом
   `window_run_id`-override).
3. **`trigger_message_id`** принимается по контракту сигнатуры, в preparation L1/L2
   не участвует (его потребитель — legacy-путь/доставка генератора, он продолжает
   получать его от вызывающего напрямую).
4. **`budget_l1` — паритет-метаданные**: резолвится тем же
   `resolve_l1_effective_budget` (с anchor-mode-зависимым system-каноном), но в
   `run_l1` НЕ передаётся: capacity-first ветка требует `budget=None` на входе —
   передача бюджета убила бы WHOLE_WINDOW/CAPACITY_OVERFLOW решение (регрессия
   режима входа). Бюджет ОДНОГО L1-запроса резолвится внутри run_l1 как раньше.
   Стоимость: один дополнительный (кэшированный) резолв на прогон.
5. Builder **никогда не бросает**: сбои резолвов слотов/бюджетов → поле
   `None`/"" (fail-open, тот же паттерн, что `_establish_source_window`).

Тяжелые импорты (clusterizer/l2_writer/budget) — ленивые, внутри функции: OFF-путь
генератора не тянет модули L2 (сохранение существующего lazy-import контракта).

### Fingerprint-инвариант (доказательство)

`fingerprint = sha256(f"{run_id}\x00{window.messages_json}")[:16]`.
`messages_json` — каноническая сериализация окна `build_source_window`
(фиксированный порядок ключей `_message_of_row`, вход-порядок строк). ⇒
для одинакового fixture (те же rows в том же порядке) и одинакового run_id
prod-путь (окно от `_establish_source_window`) и test-путь (`mount_window`)
строят байт-одинаковые окна ⇒ байт-одинаковые `fingerprint` и
`anchor_map.run_fingerprint` (`run_fingerprint(run_id, chat_id, window_from,
window_to)` — производное того же материала). Другой run_id или другой материал
⇒ другой fingerprint. Покрыто: `test_s5_same_fixture_same_fingerprint_and_anchor_mode`,
`test_deterministic_same_fixture_same_fingerprint`,
`test_sensitive_to_run_id_and_material`.

## 2. Три call-site'а

1. **Prod** `summary_generator._run_hybrid_l2`: builder вызывается один раз
   (`source_window=` от `_establish_source_window`); `run_l1(...,
   focus_block=inp.focus_block, source_window=inp.source_window)`;
   `l2_budget = inp.budget_l2` (локальный `resolve_l2_package_budget` удалён —
   одна точка резолва); `_run_writer_source_stage(..., anchor_map=inp.anchor_map,
   length=inp.length)` (новые kwargs, `None` → резолв на месте — совместимость;
   guards kill-switch + `_map_is_anchor_space` применяются как раньше). Fail-open:
   сбой builder → прежний контур (`_apply_focus`/исходный `source_window`,
   `l2_budget=None`).
2. **Test** `summary_test_run.run_summary_test`: builder с `mount_window=True`
   вместо «build_test_rows + голый run_l1» (§28.3 — отдельного preparation path
   больше нет). `run_l1(..., source_window, focus_block)`; stages["l1"] честно
   показывает `anchor_mode` / `source_window_present` / `window_fingerprint`
   (аддитивные ключи, UI-совместимо). Пакетная стадия и L2 зеркалируют живой путь:
   - map-payload (writer-source ON, тот же env-флаг
     `SUMMARY_WRITER_SOURCE_INPUT_ENABLED`) → `build_fact_view_from_map`
     (раньше map-пакет гнался через `build_fact_package` → `bad_type` →
     TEST_PACKAGE_NOT_DELIVERABLE — второй parity-дефект audit-summary §2);
   - не deliverable → `build_fallback_package` (defense, как prod);
   - L2 при writer-source: `build_l2_source_input(payload_items,
     semantic_map=map_payload, length=inp.length, anchor_map=inp.anchor_map)` +
     `run_l2(..., source_input, length, anchor_map)`; OFF → FactPackage-центричный
     вход байт-в-бит; paged L2 — как раньше;
   - рассинхрон-гейт: v1-карта (не AnchorSpace) → L2 остаётся v1
     (`map_is_anchor_space`).
   Артефакт `clusters` теперь понимает map-payload (topics; source_anchors →
   реальные id через anchor_map) — устранён симптом «Кластеры L1: 0» при
   построенной карте (audit §3.1).
3. **Replay/debug**: через `source_window=` (read-back `source_window_from_row`) +
   `window_run_id` — переопределение run_id окна/fingerprint без пересоздания строк.

## 3. map-v1 unknown-ref repair (§3.4)

`summary_l1_repair.py` — **`MapRepairReport`** (unknown_refs_count,
removed_unknown_refs, topics/events/relationships_removed, refs_before,
map_useful_after_repair, useless_reason; `as_log_fields()`) и
**`repair_semantic_map(data, id_space)`** — deterministic remover по образцу
`repair_l1`: unknown/не-int id удаляются из topics/events/relationships/
unassigned (порядок+дедуп сохраняются), опустевшие контейнеры удаляются; verdict
полезности: ≥1 тема/событие И доля различных unknown ≤ 0.5 от сосланных
(иначе `no_structure` / `mass_unknown_refs`). Вход не мутирует, повторный прогон
байт-идентичен, структурный мусор (не-dict/не-list) не решает — остаётся строгому
валидатору. **Invented refs никогда не резолвятся** (§28.4) — только удаление.

Проводка (`summary_l1_clusterizer`, map-v1 ветка, между parse и validate — тот же
kill-switch `flags.summary_hybrid_l1_repair_enabled`; OFF → прежний fail-closed
`unknown_message_id` байт-в-бит):

```text
parse → repair_semantic_map → useful → validate_semantic_map (строгий, как был)
                             → useless → invalid(l1_useless_after_repair)
                                       → РОВНО ОДИН correction retry → fail-closed
```

- `validate_semantic_map` НЕ смягчён (существующие fail-closed пины валидатора
  зелёные без правок).
- `REASON_L1_USELESS_AFTER_REPAIR` добавлен в `RETRYABLE_MAP_REASONS`
  (summary_l1_semantic_map.py) — зеркально §95-v2, где он уже retryable; новые
  reason-коды НЕ вводились (mca_events.REASON_CODES не тронут, Δ = 0 для
  активной F6-lane). v2-anchor path не затронут (его причины в этот набор не
  попадают, broken-anchor чинит локальный repair).
- `map_correction_block` дополнен веткой useless (причина + «не выдумывай id»).

## 4. Телеметрия §3.4

- INFO `L1_MAP_REPAIR | run_id | chat_id | attempt | unknown_refs_count |
  removed_unknown_refs | map_useful_after_repair | topics_removed |
  events_removed | relationships_removed | useless_reason` (R17: числа/коды).
- `MapRepairReport.as_log_fields()` → `L1Result.map_stats` (успех — через
  `MapResult.stats`, reject — напрямую в `invalid_result`; compaction мерджит
  stats, не затирает).
- Clusterizer добавляет в map_stats `retry_used`, `anchor_mode`,
  `source_window_present` (после retry-цикла).
- Генератор копирует все шесть полей §3.4 в counts `SUMMARY_L1_STAGE`
  (pipeline_events.l1_stage — сигнатура не менялась, counts свободная форма).
  Dry-run дублирует их в `stages["l1"]` своего результата.

## 5. Файлы

- NEW `services/summary_execution_input.py`, `tests/test_asap8_f2_summary_execution_input.py`
- `services/summary_generator.py` — builder-проводка, делегаты `_apply_focus` /
  `_map_is_anchor_space` (владельцы переехали: `build_focus_block` — в
  execution_input, `map_is_anchor_space` — в semantic_map; байт-та же семантика,
  существующие тесты эпика 65/anchors зелёные без правок), kwargs writer-source,
  SUMMARY_L1_STAGE counts.
- `services/summary_l1_clusterizer.py` — map-v1 repair + telemetry.
- `services/summary_l1_repair.py` — MapRepairReport + repair_semantic_map.
- `services/summary_l1_semantic_map.py` — RETRYABLE_MAP_REASONS+useless,
  map_is_anchor_space, correction-блок.
- `services/summary_test_run.py` — единый preparation path, пакетный/L2 паритет,
  clusters для map, anchor_mode/fingerprint в stages.
- Обновлённые тесты (закрепляли старый parity-дефект dry-run — §18.1):
  - `tests/test_summary_test_run.py::test_package_not_deliverable_fail_closed` —
    теперь патчит и `build_fallback_package` (dry-run зеркалит defensive-цепочку
    prod; «оба строителя недоступны» → честный skip);
  - `tests/test_cover_style_wave_b_asap4.py::test_dry_run_passes_resolver_budget` —
    смысл (сквозной бюджет T-4417) сохранён; «L2 не вызывается» больше не верен:
    fallback-пакет доставляем → L2 вызывается (как в prod);
  - version-пины 2.58.74→2.58.75 в `test_summary_test_run.py` и
    `test_summary_publish_integration_round1026.py` — пропуски релиз-гигиены
    `d204ccb` (24 файла обновлено, эти два нет), инцидентальный фикс, детали §8.

## 6. Тесты

- NEW `tests/test_asap8_f2_summary_execution_input.py` — 20 passed
  (TEST-LIFECYCLE: CONTRACT owner=ASAP8/F2):
  - S5: паритет fingerprint/anchor_mode/messages_json/budget/length prod-vs-test;
    детерминизм и чувствительность fingerprint; 0 durable-записей mount-пути;
    fail-open слотов; window_run_id (replay);
  - S6: unit repair (малый мусор, пустые контейнеры, mass-unknown, mutation-free,
    структурный мусор валидатору) + run_l1 поток (малый мусор → карта жива,
    ровно 1 вызов, телеметрия в map_stats);
  - S7: useless → ровно один correction retry → fail-closed (`l1_useless_after_repair`
    в коррекции); retry спасает карту; kill-switch OFF → прежний fail-closed
    `unknown_message_id`;
  - §28.4: invented refs удалены, не подменены;
  - dry-run audit-сценарий: anchor-путь (v2-карта строится, anchor_mode=true,
    2 вызова, 0 durable-записей) и v1-путь при anchors OFF (раньше
    TEST_L1_INVALID · unknown_message_id — теперь карта строится, мусор удалён).
- Смета прогонов (main env):
  - NEW file: 20 passed;
  - смежные focus: test_summary_test_run + test_api + epic65 + l1_repair +
    semantic_map + clusterizer + anchors_wiring + asap8_f1 + writer_source +
    generator = 353 passed;
  - **полный summary-sweep `pytest tests/ -k "summary" -q`: 1685 passed / 0 failed**
    (база F1 1665 + 20 новых; повторный прогон — тот же результат);
  - вне -k summary потребители dry-run: cover_preview, cover_style_wave_b,
    tool_coordinator, logging_runid — passed (единственный red
    `test_routes_sha256_f11_intact` — документированный пин незакоммиченного F9,
    не мой lane).

## 7. Инварианты, которые не тронуты

- Durable-окно prod: `_establish_source_window` / write-once / TTL — без изменений.
- Бюджет ≤5 генераций, инвариант вызовов L1/L2 (F1), L2-writer/reviewer — без
  изменений (builder не делает LLM-вызовов).
- Ошибки anchor/v2 map path, lossless chunking, coverage ledger — без изменений.
- R17: в логах/событиях/stages только числа, коды и sha256-хеши; никаких текстов.
- Kill-switch'и: repair OFF → прежний fail-closed; anchors OFF → v1; writer-source
  OFF → FactPackage-центричный dry-run (паритет флагов сохранён в тест-контуре).

## 8. Инцидентальные находки

1. `related, исправлено здесь`: version-пины 2.58.74 в двух summary-тестах —
   пропуск коммита релиз-гигиены `d204ccb` (он обновил 24 файла). Исправлено
   механически (см. §5); если hygiene-lane переиздаст — значения идентичны.
2. `unrelated/pre-existing, не мой lane`: `test_routes_sha256_f11_intact` —
   routes.py изменён незакоммиченным F9 (/youtube/proxy/health); переутверждение
   пина — в ревью F9 (зафиксировано в d204ccb).
3. `uncertain, не воспроизводится стабильно`: разовый fail
   `test_asap8_f6_initiative::test_wrapper_silent_turn_with_question_creates_intent`
   в 5-файльной комбинации (leaked aiosqlite connections в выводе); в изоляции,
   в 2- и 4-файльных комбинациях и повторе 5-файльной — passed (139 passed).
   Файл — незакоммиченный WIP F6-lane; к моим модулям отношения не имеет
   (рекомендация F6: проверить cross-test state).

## 9. Остаточный риск

- `budget_l1` в ExecutionInput — второй (кэшированный) резолв на прогон в auto-
  режиме; при недоступном capacity-эндпоинте возможен дополнительный WARN
  «summary budget auto: resolve failed» (fail-closed к static, прогон не рвётся).
- Dry-run в prod-конфиге теперь выполняет полный writer-source контракт (fact
  view + anchor-L2): больше кода на пути preview, но это и есть цель паритета;
  инвариант «ровно 2 LLM-вызова, 0 публикаций» покрыт тестами.
