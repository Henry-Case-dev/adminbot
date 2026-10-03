# ASAP 4.1 — conflict-audit.md (Step 1 @PM, 03.10.2026)

Сверка источника `current_task.md:22345–23844` (§0–§52) с принятыми решениями ASAP-2/2.1/3/3.1/3.2/4 и MCA-04b/05/22. Формат: принявший-документ → состояние → отношение к ASAP 4.1 → действие @Architect. **Правило:** owner-объявленные supersede фиксируются **только дословно**; PM-обнаруженные расхождения помечаются как AMEND-кандидаты и разрешаются @Architect (Builder не изобретает разрешения).

---

## 1. Owner-объявленные supersede/amend в тексте ASAP 4.1 (дословная фиксация)

| # | Дословный текст владельца | Якорь | Что отменяет/меняет |
|---|---|---|---|
| 1 | «Запрещено использовать как основной механизм: messages[:N], last N messages, 50000 chars, fixed 20k/30k token cap, "возьмём самые важные 300"» | 22410–22418 | Запрет касается **новых механизмов выборки истории**; сам 50k-хвост `summary_xml.py:76` уже снят ASAP-4 (R4-C-008) — см. п.4 |
| 2 | «Нельзя делить текст на чанки просто потому, что "раньше так было безопаснее"» | 22469 | Направлено на chunking/sharding-first из ASAP-4 зоны C — AMEND-кандидат #1 (ниже) |
| 3 | «Не использовать: if "deepseek" -> 1000000 … как основной механизм» | 22530–22537 | Ограничивает name-based карту `MODEL_CONTEXT_WINDOWS` (ASAP-3.1) уровнем реестра — AMEND-кандидат #2 |
| 4 | Требование §22 «timeout = 120 seconds … плохой контракт», §23 «Убрать вложенные: stage retry × llm_client retry × provider retry × fallback retry» | 22983, 23011–23018 | Меняет тайминг/ррretry-контракт `llm_client.py` для Summary — AMEND-кандидат #3 |
| 5 | «Переименовать misleading `total_budget_exceeded`» | 23187 | Reason-code rename (владелец указывает целевые имена: `execution_deadline_exceeded` / `retry_time_budget_exhausted` или «другой однозначный») |
| 6 | «Заменить [Source → L1 → FactPackage → L2] на [Full SourceWindow + SemanticMap → Writer]» (§11); «FactPackage перестаёт быть обязательным payload Writer» (§15) | 22694–22700, 22798–22820 | Меняет контракт Writer'а из ASAP-4 зоны D (там Writer получал FactPackage-центричный вход) |
| 7 | §31 «Запрещён: hard cap 50000 chars → stop» для Legacy | 23208–23213 | Ужесточение ASAP-4 (R4-C-007/008 уже сняли silent-stop; §31 требует capacity-aware legacy со 100% coverage в обеих ветках) |
| 8 | §51 «Обычному админу не нужны: L1_CHUNK_SIZE, L2_TIMEOUT, MAX_INPUT_CHARS, SUMMARY_CONTEXT_TOKENS» | 23777–23782 | Класс новых настроек не создаётся; developer-настройки прячутся в deep settings |

**Итог:** дословных указаний «supersede ADR-XXXX» в §0–§52 нет — владелец даёт прямые архитектурные директивы «заменить/запрещено/переименовать» (п.1–8). Формальные supersede-записи в ADR/ARCHITECTURE оформляет @Architect (прецедент R4-D-065).

## 2. AMEND-кандидаты PM (разрешает @Architect, до этого — не помеха Builder'у в открытых зонах)

| # | Принятое решение (документ) | Конфликт с ASAP 4.1 | Статус | Действие |
|---|---|---|---|---|
| AM-1 | **ASAP-4 зона C / ADR-1028-7 D7.1** (`summary_l1_capacity.py`, T-4422): planning-estimate шардит окно **до** L1-запросов, чтобы не словить `too_many_facts` на whole-window L1 («защитная» сегментация при полном контексте) | §3/§6/§8: chunking разрешён **только** когда модель физически не вмещает SourceWindow; решение — по реальному serialized prompt, а не по прогнозу плотности фактов | **Реальный конфликт** | AMEND ADR-1028-7 D7.1: триггер сегментации меняется с «планируемой semantic density» на «реальную capacity». Открытый вопрос @Architect (перенести в spec): как в WHOLE_WINDOW удерживается компактность L1 (§12 semantic map без source payload) и не возвращается ли `too_many_facts`-invalid; согласовать контракт `MAX_FACTS_PER_THREAD=30` (ASAP-4: structural ceiling, не semantic guillotine — R4-D-036) с one-request L1 |
| AM-2 | **ASAP-3.1** (`model_capacity.py`): карта `MODEL_CONTEXT_WINDOWS` — name-based; известный хвост unknown_fallback=16384 (backlog Follow-up ASAP-3, п.1) | §5: name-mapping — не основной механизм; цепочка приоритетов 1–5; §6: считать по serialized prompt, включая output reserve/framing | **Уточнение, не отмена** | Карта становится уровнем 3 (project registry); консервативный fallback — уровнем 5; добавить runtime discovery (1) и metadata (2) |
| AM-3 | **llm_client.py** (Epic 47/53, ADR-1024-6): `LLM_TIMEOUT` (120s), `LLM_MAX_RETRIES` + backoff + `LLM_FALLBACK_MAX_RETRIES`, `LLM_TOTAL_BUDGET` | §22–§26: wall-clock — не основная метрика; один Supervisor владеет retry/fallback/deadline; убраны вложенные циклы | **Реальный конфликт для Summary-пути** | Границы: ASAP 4.1 меняет тайминги **Summary-пайплайна**; прочие потребители llm_client (Direct, STT, image, embeddings) не трогаются без причины — решение @Architect об объёме (supervisor как wrapper level vs модификация client). Transport-retry нижнего слоя vs «no retry multiplication» — посчитать фактические максимумы попыток (прецедент R4-A-004/Q) |
| AM-4 | **ASAP-4 зона D**: Writer вход = FactPackage-центричный пакет (FactPackage + evidence index), Reviewer сверяет против FactPackage/SourceRefs | §11/§15/§16/§17: Writer и Reviewer получают **Full SourceWindow** как первоклассный вход; FactPackage — опциональная derived view | **Уточнение входного контракта** | Расширение WriterInput/ReviewInput: source_window обязателен; валидатор/Reviewer-правила сверяются против оригинала (§47-сценарии). Обратной совместимости промптов — отдельная проверка (прецедент R4-D-003: менять prompt явно) |
| AM-5 | **ASAP-2/ASAP-4**: «L1_FALLBACK_PACKAGE / FACT_PACKAGE_TRUNCATED» — fallback-механика пакетов | §0 перечисляет эти коды среди симптомов инцидента; §14: partial-success сохраняет успешные maps + deterministic minimal map; полный fallback-package при падении L1 больше не единственный путь (Writer берёт SourceWindow напрямую, §13) | **Деградация меняется структурой** | Не отмена события, а изменение роли: fallback-package остаётся derived view (§15), Summary не должен сводиться к нему; сверить reason-коды §42 |
| AM-6 | **post-asap4 corrective pass** (в процессе): порядок «текущий pass → deploy+acceptance → ASAP 4.1 целиком» | Зависимость старта Builder'а 4.1 от закрытия pass'а (T-4508–T-4510) | **Учтено в порядке волн** | Порядок зафиксирован в tasks.md; планирование 4.1 (docs-only) идёт параллельно, Builder — после деплой-гейта pass'а |

## 3. Сверка с эпиками-источниками (без конфликтов / reuse)

| Эпик (архив) | Принятые решения | Отношение к ASAP 4.1 |
|---|---|---|
| **ASAP-2** (`mca-asap2-summary-pipeline`) | Hybrid L1/L2, L1/L2 schema, fail-soft unknown L1 IDs, S7 run_id | Сохраняется; S7 run_id — основа для событий §42 и SummaryRun. Сверх «L2 unusable → Legacy» уже superseded ASAP-4 (R4-D-001); 4.1 ничего не откатывает |
| **ASAP-2.1** (`mca-asap21-summary-quality-ui-cleanup`) | Удаление алгоритмической предфильтрации source (R4-D-038 подтверждает) | Сохраняется напрямую: SourceWindow — сырые сообщения + разрешённый cleanup/metadata; §2-схема включает media-derived text «if already available» — не вводить новую предфильтрацию |
| **ASAP-3** (`mca-asap3-direct-context-reply-reliability`) | Direct-контур, контекст-лимиты Direct | Не пересекается по скоупу; общие llm_client-гейты не ломать (AM-3); M-ASAP31-2 (tool-loop fallback payload) остаётся carry-over, НЕ входит в 4.1 |
| **ASAP-3.1** (`mca-asap31-auto-budgets-capacity-react`) | Auto Budgets, capacity, `MODEL_CONTEXT_WINDOWS`, REACT | AM-2 + REUSE: capacity resolver расширяется, не дублируется; хвосты L-ASAP31-1…3 (шум событий read-side, capacity.runtime=None) — учесть в §42-дизайне событий, чтобы не рождать новый шум |
| **ASAP-3.2** (`asap-32-runtime-reliability`) | MediaExecutionPolicy D4–D7 (adaptive windows, job state, adapter capabilities), honest terminal vs paused | REUSE: паттерн-донор для LLMExecutionSupervisor (media_execution.py). Не дублировать: один контур исполнения, Supervisor для Summary LLM, Media-политика остаётся для image |
| **ASAP-4** (`asap-4-embedding-graphrag-cover-runtime`) | Зоны A (embedding control plane), B (cover style), C (L1 capacity/Legacy full-window/quote repair), D (Writer/Reviewer bounded revision), E (Analytics); kill-switch-дисциплина; no-false-quality (R4-D-064) | Зоны C/D — основа 4.1 (см. reuse-inventory §3); AM-1/AM-3/AM-4 — оформляемые уточнения; R4-D-064 (no-false-quality) прямо повторён §0 («Нельзя считать этот запуск успешным…») и §38 |
| **MCA-04b** (`mca-04b-dossier-rebuild`) | ADR-1027-9: dossier rebuild keyset/batch, real-pool discipline, task_jobs | Конфликтов нет: разные контуры (dossier vs Summary). Совместное использование task_jobs — учесть L-EXTRA-6 (payload/checkpoint-колонка) в дизайне SummaryRun |
| **MCA-05** (`mca-05-episodes-stories`) | ADR-1027-12: episodes/stories v21, worker-budget инварианты | Конфликтов нет: episodes.build — отдельный LLM-контур; если Supervisor 4.1 становится общим для background-LLM — границы решает @Architect (по умолчанию scope = Summary) |
| **MCA-22** (`mca-22-attribution-memory-coherence`) | ADR-1028-6 D1–D10: D3 Quote Resolver (публичный interface), identity stack, kill-switches | Согласовано в ASAP-4 (extension, не fork). §17/§47 4.1 усиливают сверку против SourceWindow — это потребителей D3-resolver'а не ломает, а снабжает более полным источником; write-интерфейсов MCA-22 не трогаем |

## 4. Orphan-проверка и несводимость

- Orphan-требований нет: каждый §0–§52 покрывает ≥1 R6-ID (см. requirements-map.md); DoD 35/35 имеет задачи.
- Обратных противоречий («владелец запрещает то, что ранее прямо просил») не обнаружено: §18/§19 явно сохраняют идеи ASAP-4; §31 сохраняет Legacy; §32 сохраняет MAX_SUMMARY_PARTS.
- Циркулярных зависимостей задач нет: граф в tasks.md — DAG (аменды ADR → Builder-волны → тесты → release).
- Критерии наблюдаемы (metrics/events/UI/evidence); «честная приёмка» операционализирована чек-листами §48/§49.
- Скрытое ограничение для @Architect: §25 требует «hard deadline зависит от operation/model/input» — конфликтует с постоянными hot-config-числами из §51 (L2_TIMEOUT-класс); глубокие developer-настройки — единственное легитимное место (это согласуется, но формулирует контракт настроек).
