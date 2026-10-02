# ASAP-4 — conflict-audit.md (Step 1 @PM, 02.10.2026; требование владельца §82, current_task.md:20593–20608)

Сверка ASAP-4 с закрытыми/активными эпиками. Принцип: **не создавать parallel implementation**; `PLANNING_CONSISTENT` выдаётся только после этой сверки. Статусы сверяемых эпиков взяты из `plans/backlog.md` и `plans/workflow_state.md` (факт на 02.10.2026).

Итог сверки: **прямых неразрешимых конфликтов нет.** Найдено: 3 owner-declared supersede (оформляются ADR), 3 deliberate AMEND-зоны (решения @Architect), 1 фактическая рассинхронизация текста ТЗ с реальностью (MCA-22 уже закрыт — трактовка зафиксирована ниже), 8 пересечений с открытыми хвостами (см. reuse-inventory.md §4).

---

## 1. ASAP-2 / ASAP-2.1 (`mca-asap2-summary-pipeline`, `mca-asap21-summary-quality-ui-cleanup` — RELEASED + ARCHIVED)

| Контактная точка | Статус | Действие ASAP-4 |
|---|---|---|
| ADR-решение «L2 unusable → сразу LEVEL-3 Legacy» и кодовый контракт `summary_generator.py` «L2 correction retry НЕ вводится» | **SUPERSEDED владельцем** — §50.1 (`current_task.md:17741–17756`) явно: «Это новое owner-level решение сознательно заменяет старое ASAP-2 решение» | Zone D строит bounded revision loop; обязанность @Architect — процедура §50.65: найти старое решение, зафиксировать supersede, bounded contract, обновить ADR/Architecture, сохранить rollback (`current_task.md:19355–19369`) |
| Правило L2 prompt «Прямые цитаты не приводи» | **SUPERSEDED владельцем** — §50.3 (`current_task.md:17822–17845`): «Prompt migration должна изменить это правило явно» | Миграция промпта prose-first/quote-allowed (R4-D-003); старый канон-промпт пометить в эталонах (правка эталона = код+эталон+тесты одним коммитом, project.md) |
| ASAP-2.1: удаление алгоритмической предфильтрации source | **ДЕЙСТВУЕТ** — §50.38 (`current_task.md:18725`): «ASAP-2.1 решение … сохранить» | Не восстанавливать предфильтрацию; регресс-тесты остаются зелёными (R4-D-038) |
| Fail-soft unknown/malformed L1 IDs (ASAP-2) | **ДЕЙСТВУЕТ** — §50.35 (`current_task.md:18646–18657`) | Сохранить контракт (R4-D-035) |
| Событийная модель SUMMARY_*/FORMAT_*/COVER_* (S7/ADR-1026-9, PUBLISH_* gated S6/D4) | ДЕЙСТВУЕТ | Zone E строит normalized events поверх неё (§61.11), не заменяя; аддитивные новые события по прецеденту S7 |

## 2. ASAP-3 / ASAP-3.1 (`mca-asap3-direct-context-reply-reliability`, `mca-asap31-auto-budgets-capacity-react` — RELEASED + ARCHIVED)

| Контактная точка | Статус | Действие ASAP-4 |
|---|---|---|
| Auto Budgets / context windows / `MODEL_CONTEXT_WINDOWS` (`services/model_capacity.py`) | ДЕЙСТВУЕТ | Zone C опирается на capacity/budget resolver; не дублирует (R4-C-002 planning estimate — аддитивно к чанкингу) |
| Full-window/chunking contracts, `MAX_SUMMARY_PARTS` | ДЕЙСТВУЕТ — §58 (`current_task.md:19596`) прямо: «не трогать» | Паритет (R4-C-010) |
| Follow-up L-ASAP31-4: dry-run `summary_test_run.py:590` без resolver-бюджета | Открытый хвост | Пересекается с R4-B-005 (единый resolver test/prod) — включить при касании тест-контура (не отдельный эпик) |
| Follow-up п.5 «семантика FACT_PACKAGE_TRUNCATED» (per-topic cap vs бюджет) | Открытое исследование владельца | Совпадает с контуром R4-D-031/032 — закрыть одним контрактом в зоне C/D |
| Follow-up M-ASAP31-2 (tool-loop fallback payload) | Открытый хвост | Вне scope ASAP-4 (Direct-контур) — остаётся в backlog |

## 3. ASAP-3.2 (`asap-32-runtime-reliability-round1029` — RELEASED + VERIFIED 2.58.40 + ARCHIVED; ADR-1028-5 D1–D14 Accepted)

| Контактная точка | Статус | Действие ASAP-4 |
|---|---|---|
| Зона 1: lifecycle GraphRAG (D1/D3) + честный терминальный `failed` при исчерпании лимитов (прод-валидация D1–D14, Follow-up п.1: `graph_facts_vec` gen=1 failed на 429 после checkpoint 2500/15013) | **AMEND-зона**: §24 (`current_task.md:17129`) требует 429 → `paused_rate_limit`, не immediate terminal; §25 допускает terminal только при исчерпании bounded retry horizon | @Architect оформляет AMEND ADR-1028-5 (или новый ADR): пауза/resume вместо быстрого terminal при 429; checkpoint/attempt history; resumable-механика D2 сохраняется и становится основной |
| Зона 2: MediaExecutionPolicy (D4–D7) | ДЕЙСТВУЕТ | Zone B переиспользует; нового media-контракта нет |
| Зона 3: provider discovery / capacity resolver | ДЕЙСТВУЕТ | Zone A adapter строится поверх |
| Зона 4: hierarchical semantic reduction (D8/D9) | ДЕЙСТВУЕТ | Zone C/D переиспользуют `services/summary_semantic_reduction.py` для §50.31/§51; coverage-метрики расширяются аддитивно (§50.32) |
| Зона 7: Analytics actual snapshot + GraphRAG health (D12/D13) | ДЕЙСТВУЕТ | Zone E расширяет те же виджеты (embedding-панель §32/§62 — эволюция GraphRAG health) |
| Зона 8 EXTRA: Cover Style connection model / seed / UI / PG contract (D14) + hotfix 2.58.43 | ДЕЙСТВУЕТ | Zone B не ломает PgDatabase-vs-Pool контракт; хвосты L-EXTRA-6/7/rowcount — при касании |
| Тест-хвост N-ASAP32-6 (validate↔activate не выделен в отдельный тест) | Открытый хвост | Zone A тесты активации (R4-A-028) закрывают естественно |

## 4. MCA-07 retrieval (`mca-07-retrieval-context` — RELEASED + ARCHIVED; ADR-1027-7, DDL v18)

| Контактная точка | Статус | Действие ASAP-4 |
|---|---|---|
| `mca_embedding_index_generations` (v18) — реестр поколений embedding | ДЕЙСТВУЕТ | Zone A: едиственный реестр; новые поля (quota group state, attempt history) — только через MigrationStep, аддитивно |
| N-MCA07-1 (API активации поколения) → реализовано в mca-04b | ДЕЙСТВУЕТ | Zone A activation criteria (§30) согласуется с существующим activation API; не создавать второй |
| Каналы retrieval-контракта (exact/lexical/reply_graph/episode-lore/vector) | ДЕЙСТВУЕТ (fail-open закрыт 2.58.36) | Zone A не меняет контракт retrieval; vector-канал оживает через ACTIVE |

## 5. MCA-17 Analytics (`mca-17a-observability-core` — RELEASED + ARCHIVED; ADR-1027-8, DDL v19)

| Контактная точка | Статус | Действие ASAP-4 |
|---|---|---|
| `mca_events` / `mca_pipeline_runs` / lifecycle 9 состояний / run partial/degraded/stalled | ДЕЙСТВУЕТ | Zone E: normalized stage events (§61.11) отображаются на существующую модель (mca_pipeline_runs + события), не создаётся «отдельная аналитика с собственной истиной» (§61.11 прямо запрещает, `current_task.md:20052–20056`) |
| Запрет нового корневого dashboard (прецедент MCA-22 reuse matrix) | ДЕЙСТВУЕТ | R4-E-002: «в существующей Analytics, не новый отдельный продукт» |
| `services/mca_events.py:REASON_CODES` — расширяемый словарь | ДЕЙСТВУЕТ | Новые reason codes (KNN §28, quote §53.1, style §42, reviewer §50.12) — в этот словарь, не в новые словари |

## 6. MCA-22 (`mca-22-attribution-memory-coherence-round1029` — RELEASED + VERIFIED 2.58.44 + ARCHIVED 02.10.2026; ADR-1028-6 D1–D10)

| Контактная точка | Статус | Действие ASAP-4 |
|---|---|---|
| Текст ТЗ §2 (`current_task.md:16619–16631`): «MCA-22 остаётся отдельным **будущим** интеграционным Epic» | **ФАКТИЧЕСКАЯ РАССИНХРОНИЗАЦИЯ**: MCA-22 уже закрыт и архивирован (backlog.md:15). Трактовка PM: скоуп-запрет владельца остаётся в силе как запрет **дублировать** MCA-22-зоны в ASAP-4; формулировка «будущий» морально устарела — в spec не переносить дословно | Zone A обеспечивает serviceable retrieval; зоны canonical speaker/Own Output Ledger/quote resolver/correction/freshness в ASAP-4 НЕ входят |
| ADR-1028-6 **D3 Quote Resolver** (единая детерминированная лестница 1–7, уже в проде) | **AMEND-зона/REUSE**: ASAP-4 вводит quote validation/repair в Summary L2 (§50.20, §53.1, §53.2). Риск параллельного resolver'а | @Architect обязан в spec явно разрешить: Summary-локальная проверка цитат переиспользует/согласуется с D3-лестницей (текст/speaker/source), второй resolver не создаётся; где лестница не покрывает L2-случаи — extension, не fork |
| §50.9 «До будущего MCA-22 здесь не строим второй глобальный identity stack» | MCA-22 построен; identity (MCA-03 v16 + C1/C4/C5) в проде | Zone D reuses существующие metadata (author_id/roles/quote_author_id) — не строит второй identity stack (теперь не «до MCA-22», а «поверх закрытого») |
| MCA-22 reuse matrix: «ASAP-3/3.1/3.2 … не трогаются» | ASAP-4 owner-mandated **расширяет** embedding/provider lifecycle | Это не конфликт, а deliberate scope extension владельцем; зафиксировать в новом ADR как связь с ADR-1028-6 (quote resolver consumers) |
| Kill-switches MCA-22 (4 env-only) | ДЕЙСТВУЕТ | Zone D не влияет на них; OFF-паритет собственных рубильников ASAP-4 — санкция @Architect |

## 7. MCA-23 (`mca-23-unified-response-orchestrator` — PLANNED/HOLD, current_task.md:20833–20861)

| Контактная точка | Статус | Действие |
|---|---|---|
| Порядок: ASAP-4 → acceptance → MCA-очередь → MCA-21 → MCA-23 последним | HOLD, в план не включён | В Wave-план не входит; interface-совместимости с MCA-23 не требуем; integration notes — только если появятся (правило `current_task.md:20859`) |

## 8. Сводка supersede / amend (для @Architect)

1. **SUPERSEDE (owner-declared):** «L2 correction retry НЕ вводится» / «L2 unusable → сразу Legacy» → bounded revision loop (§50.1 + §50.65, R4-D-001/065).
2. **SUPERSEDE (owner-declared):** prompt-запрет прямых цитат → prose-first/quote-allowed (§50.3, R4-D-003).
3. **AMEND (архитектурный):** политика 429 у GraphRAG rebuild: honest terminal (ADR-1028-5) → paused_rate_limit + resume same generation (§24/§25/§27) — оформить AMEND/new ADR.
4. **REUSE/EXTENSION (архитектурный):** Summary quote validation поверх MCA-22 D3 Quote Resolver — без второго resolver.
5. Остальных запрещённых supersede нет: MAX_SUMMARY_PARTS, prefilter-удаление ASAP-2.1, fail-soft L1 IDs, gemini-embedding-001, FTS fail-soft — сохраняются как есть.

## 9. Orphan / противоречия в самом ТЗ (фиксация PM, не разрешение)

- Нет: все 5 зон имеют владельческие критерии; orphan-требований не обнаружено.
- Помечено: R4-A-032/§34 допускает «долгую» альтернативу ACTIVE — критерий приёмки должен явно выбирать ветку evidence (scheduler-доказательство vs full ACTIVE) — уточнение @Architect в spec.
- §48/§78 (real Medved Press acceptance) зависят от owner-precondition DC-4 (настроенный платный image-connection) — в tasks помечено как owner-гейт.
