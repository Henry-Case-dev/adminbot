# MCA-06 — reuse-inventory.md (Step 1 @PM, 03.10.2026)

Инвентарь переиспользования. Правило GEN-R19 (`plans/docs/mca-round1027-plan.md:43`): реализовано — проверить и переиспользовать; REUSE-заявки ниже сверены с фактическим кодом на 03.10.2026 (прод 2.58.47, SQLite v24). Всё — логические компоненты внутри текущего приложения, без микросервисов (GEN-R21).

## 1. Собственная реализация сна (сохранить и дополнить — :344)

| Компонент | Файл/факт | Что переиспользуем | Что дополним |
|---|---|---|---|
| DreamWorker | `services/dream_worker.py` — `_run_deep_once` (:1514), `_write_paradigm` (:2032), `_deep_dedup_key` (:2135), запись beliefs с `source_ids` JSON | Воркер, тик, расписания, окна, кластеризация — владельцем «сохранить» (:344) | Происхождение и проверка выводов; статусы; cooldown/backoff-разделение; отчёт прогона |
| Промпты сна | `services/dream_prompts.py` — канон `DEEP_SLEEP_BRIDGE_SYSTEM_PROMPT` (:154), `parse_bridge_answer` (:237) — эталон-уровень (сверено round1021 spec §2.1) | Канон мостов «раньше → сейчас» как есть | Валидационные поля (субъект/время/противоречие) — правка промпта только явно, одним коммитом «код+эталон+тесты» (прецедент R4-D-003) |
| UI/API сна | `web/api/memory_agi.py` — `/api/memory/dream*`, `is_paradigm` (:272–275) | Существующие эндпоинты | Разделение `master_off` (:509), честные статусы, раскрытие цепочки |
| Настройки сна | каталог: `memory.dream_*` (11 ключей), `flags.deep_sleep_enabled`, `limits.deep_sleep_*` (`plans/docs/param-registry-round1025.tsv:176–178,319–334`) | Все ключи как есть | Новые sleep-gates-ключи — только санкцией @Architect (Δ каталога; кандидат в открытый вопрос плана, `mca-round1027-plan.md:404`) |

## 2. Wave-зависимости (закрыты — round 1027/1029)

| Источник | Артефакт | Использование в mca-06 |
|---|---|---|
| **mca-04a provenance** (§98, ADR-1027-6) | `services/provenance.py`: `SourceRef`/`EvidenceLink`, `message_source_ref` (:190), `graph_fact_source_ref` (:182), `resolve_source_ref` (:288), `add_evidence_link` (:305), `record_source_ids_provenance` (:899); таблицы `mca_source_refs`/`mca_evidence_links` (DDL v17); backfill belief/paradigm `source_ids` уже сделан (T-3821/T-3823, dream-канал provenance в `dream_worker.py:2066–2072`) | Типизация **обеих** групп ссылок парадигмы (:346) через существующий контракт — второй контракт не создаётся (дословно `current_task.md:15371`). Исторические `anchor_items` — недостающая половина (REUSE + расширение, не fork) |
| **mca-17a observability** (§100, ADR-1027-8) | `services/mca_events.py` (REASON_CODES), `mca_process_registry.py`, `mca_trace.py`, `mca_watchdog.py`, `mca_incidents.py`; DDL v19 `mca_pipeline_runs` | Регистрация процессов/стадий сна в реестре, trace/span, отчёт прогона как run-стадии, инциденты на недоступные основания; GEN-R17-данные для будущей витрины `mca-17c` |
| **mca-05 episodes** (2.58.42, ADR-1027-12) | `services/mca_episodes.py` (+`mca_episode_jobs.py`/`mca_episode_prompts.py`) — **файлы так называются; модуля `episode_service` нет (сверено glob)**; события `story_*`; v21 | Эпизоды как кандидаты исторических оснований (:375 «старые факты, эпизоды и доступные первичные сообщения»); учесть: таблицы v21 пусты до запуска владельцем live-извлечения → no_anchors/enrichment-путь обязан корректно работать на пустом пуле |
| **mca-03 identity** (§96, ADR-1027-4) | v16 identity-колонки `smart_messages`, canonical source, `chat_id+tg_message_id` | Якоря/сообщения в раскрытии цепочки — до стабильных идентичностей; дата события ≠ дата импорта (:368) |
| **mca-07 retrieval** (§99, ADR-1027-7) | `services/mca_retrieval_context.py`; каналы exact/lexical/reply_graph/episode-lore/vector (fail-open снят релизом 2.58.36) | Исторический поиск кандидатов — специализированный вызов поверх тех же каналов с фильтром возраста/scope ДО top_k (:373); не менять смысл direct-RAG, не обходить ACL (:376) |
| **mca-22 attribution** (2.58.44, ADR-1028-6) | Семантика `supersedes/contradicts` EvidenceLink, reason_codes, Quote Resolver, `services/bot_output_ledger.py` (собственные ответы бота — не независимое подтверждение) | Версии парадигм (:380) и анти-самоподтверждение (:352); bot-вывод в пересказе не считается независимым (REUSE bot_output_ledger) |

## 3. Архивные прецеденты

| Источник | Что берём |
|---|---|
| **paradigm-thresholds-consolidation-round1021** (`plans/archive/paradigm-thresholds-consolidation-round1021/`, ADR-1021-4, ACCEPTED) | Факт-база: парадигмы = `graph_facts` c `belief_meta.type='paradigm'` (таблицы `paradigms` нет); пороги/капы (`DEEP_SLEEP_TOP_K=20`, `MAX_PARADIGMS=3`, `TOKENS_PER_DAY=40000`) и их миграция дефолтов (`migrate_dream_thresholds`); консолидация — CLI-only F5, авто-крона нет; наблюдаемость `memory_health.collect_metrics` (`paradigms_total`, `paradigms_last_run`, `deep_sleep_skipped_reasons`). **Пороги не снижаем** (:377) — снимаем только обрывы гейтов/поиска |
| **cognition-deep-sleep-round1013 / dead-extractor-paradigms-round1024 / memory-rebuild-sanitation-round1021** (архивы) | Исторические решения по deep-sleep ветке, защита опор живых beliefs/парадигм (`memory_rebuild.py` S10.21-3), sanitation-границы |
| **asap-4-1-durable-whole-window-summary-round1031** (ADR-1028-8, Accepted, 2.58.47) | Паттерн-донор: durable run-отчёт со стадиями (аналог SummaryRun), honest-status дисциплина («ошибка ≠ пустая выдача» — зеркально no-false-quality), kill-switch-дисциплина env-only default ON, capacity-first подход к большому serialized prompt. **Scope-донор, не fork:** Supervisor в 4.1 — Summary-only (AM-3); подключение DreamWorker к Supervisor — AMEND-кандидат за @Architect (см. conflict-audit) |
| **round1022-human-gate-map** (`plans/archive/round1022-human-gate-map.md`) | «Уже выданное разрешение MCA на включение памяти и функций» (:374) — не создавать повторный human gate |
| **feature-gates-worker-budget** (архив) | Worker-budget дисциплина фоновых контуров; бюджетные кулдауны сна (`deep_sleep_tokens_per_day`) не дублируются |

## 4. Анти-реюз (что НЕ создавать)

- Второй provenance-контракт или параллельную таблицу парадигм — запрещено дословно (`current_task.md:15371`).
- Второй effective-gate resolver для сна параллельно `mca_gates.py` — единый resolver на 4 потребителя (:374).
- Второй контур инициативы/исследований вне `mca-10b` (§14.5–14.11 — не здесь); визуализация снов — не mca-06.
- Новую цепочку ретраев параллельно `llm_client` (дисциплина ADR-1028-8 AM-3) — только если Architect решит расширить Supervisor-скоуп, явно.
- Конкурирующий каталог историй/эпизодов (дословно :332, §9.2 — интеграция, не второй каталог).

## 5. Заявки на Step 2 @Architect (sanction-кандидаты)

1. **Δ DDL:** ожидание PM — 0…аддитивные nullable-колонки/поля отчёта прогона; typed anchor-ссылки укладываются в v17-таблицы (`mca_source_refs`/`mca_evidence_links`); стадийный отчёт сна — кандидат в `mca_pipeline_runs` (v19). Финальное решение — spec/ADR.
2. **Δ каталога:** possibly > 0 (sleep-gates — открытый вопрос плана, `mca-round1027-plan.md:404`); если да — F8-переиздание по ADR-1026-2.
3. **Kill-switches:** имена `MCA_DREAM_*`-класса (env-only, default ON), OFF-паритет байт-в-байт (прецедент mca-05 `MCA_EPISODES_ENABLED`).
4. **RandomSource-интерфейс:** случайный выбор материала/гипотезы (:356) — детерминированная заглушка/интерфейс до Wave 3 `mca-10a`; смена источника — при активации mca-10a, без переписывания пайплайна.
5. **Supervisor-scope:** deep-sleep LLM-вызовы остаются под существующими бюджетами/таймингами воркера; перенос под LLMExecutionSupervisor — решение @Architect (см. conflict-audit CA-6).
