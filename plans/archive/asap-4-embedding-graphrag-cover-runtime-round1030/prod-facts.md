# ASAP-4 — prod-facts.md (Step 2 @Architect, 02.10.2026)

Ответы на обязательные вопросы владельца §81 (Q1–Q37), `current_task.md:20472–20589`.
Формат: **Q1–Q17 — факты с прода** (journalctl / sqlite read-only / код 2.58.44), **Q18–Q37 — решения по коду/дизайну** (детализация в `spec.md` + `adr-1028-7`).

Источники:
- прод: `ssh nik@198.46.175.136`, сервис `admin_bot.service` (WorkingDirectory=/var/www/admin_bot, один процесс `bot.py`, PID 2796224, старт 01.10 16:19 UTC);
- журнал: `journalctl -u admin_bot` (время = UTC), выдержки ниже с теймстампами;
- БД: `/var/www/admin_bot/local_database.db` (SQLite `user_version=22`), подключение строго `mode=ro`; `sqlite3`-CLI на хосте отсутствует — запросы через venv-python + `sqlite_vec` (import подтверждён);
- конфиг: имена env-переменных из `/var/www/admin_bot/.env` (значения ключей НЕ читались и не логировались);
- код: рабочее дерево 02.10.2026 (= прод 2.58.44, версия-строка из хотфикс-истории ADR-1028-5).

Ключи упоминаются только как алиасы (primary / fallback#1 / fallback#2).

---

## Часть I. Q1–Q17 — прод-факты

### Q1. Три Gemini key: один project/quota group или разные?

**Факт (конфиг, без секретов):** prod `.env` содержит ровно 4 EMBEDDING-строки: `EMBEDDING_BASE_URL`, `EMBEDDING_MODEL_NAME`, `EMBEDDING_FALLBACK_API_KEY`, `EMBEDDING_FALLBACK_API_KEY_2`. Primary-ключ резолвится из PG hot-config `keys.embedding_api_key` (`services/llm_client.py:406-410`, env `EMBEDDING_API_KEY` на проде пуст — `settings.py:360`), fallback-ключи — из env. Все три credential ходят на один endpoint `https://generativelanguage.googleapis.com/v1beta/openai/embeddings` (подтверждено логами: каждый 429-рейз указывает этот URL).

**Факт (код):** `config/settings.py:397-399` — комментарий ко второму fallback-ключу: «ВТОРОЙ запасной ключ embed-фоллбэка (Google AI Studio, **запасной аккаунт** — тот же endpoint/модель)» → key#2 принадлежит другому Google-аккаунту, т.е. минимум 2 разных аккаунта. Проектная принадлежность key#1/primary с сервера не выводится.

**Ответ:** 3 credential; независимых quota-групп **точно не «3», вероятно 2** (primary+fallback#1 в одном аккаунте — предположение, fallback#2 — другой аккаунт — по комментарию кода). Machine-readable доказательства принадлежности к project на проде нет → в терминах §5 группа = `unknown` до явного developer-label; scheduler по умолчанию обязан считать все ключи **одной** группой (безопасный минимум), разгруппировка — только через явный label. UI: «Проект/квота: не определены».

### Q2. Сколько HTTP calls делает один логический `_embed()` при полном каскаде?

**Факт (код 2.58.44):** каскад сохраняется в точности как в ТЗ §6:
- внешний ретрай: `services/summary_memory.py:282` `_EMBED_RETRY_ATTEMPTS = 3`, цикл `:1714-1725` (backoff 1.0·2ⁿ);
- внутри `LLMClient.embed` (`services/llm_client.py:1317-1362`): primary `_post` с `LLM_MAX_RETRIES=2` (`settings.py:381`) → **3 попытки**; затем 2 fallback-ключа (`_embed_fallback_api_keys`, `:371-373`), каждый `_embed_fallback_with_retries` с `EMBEDDING_FALLBACK_MAX_RETRIES=1` (`settings.py:406-407`) → **2 попытки на ключ**.

**Ответ:** максимум `3 × (3 + 2 + 2) = 21` HTTP-вызов на один логический embedding-батч. Формула подтверждена на актуальном коде, не только в архиве.

### Q3. Есть ли вложенный retry amplification после ASAP-3.2?

**ДА, подтверждён продой.** Живой шторм 01.10.2026 19:26:21–19:27:56 UTC (journalctl, PID 2796224) — повторяющаяся связка:

```text
19:26:21 LLM embed fallback attempt | key_idx=0 | primary_error=LLMRateLimitError: (429) after 3 attempts
19:26:22 LLM embed fallback retry | attempt=2/2 | reason=status=429
19:26:23 LLM fallback failed | kind=embed | error=status=429
19:26:23 LLM embed fallback attempt | key_idx=1 | ...
19:26:24 LLM embed fallback exhausted | keys=2 | reason=Рейт-лимит (429) — воркер ждёт и повторит…
19:26:24 summary_memory - WARNING - embed attempt failed | attempt=2/3 | ...
19:26:33 summary_memory - ERROR - embed failed after 3 attempts
Traceback: services/summary_memory.py:2868 in _save_graph_fact_embedding → LLMRateLimitError
```

Паттерн `attempt 1/3 → 2/3 → 3/3` повторяется в журнале десятки раз подряд — внешний ретрай (`summary_memory`) поверх key-каскада (`llm_client`) поверх HTTP-ретраев (`_post`) — всё живо. ASAP-3.2 embed-путь не трогал (его зона была lifecycle/rebuild), поэтому amplification сохранён. Шторм 19:26–19:27 — это **live write-путь** (`_save_graph_fact_embedding`), не rebuild: P1-трафик страдает вместе с P3.

### Q4. Учитывается ли `Retry-After` без вредного cap?

**НЕТ.** `services/llm_client.py:646-661`: Retry-After парсится, но жёстко капится: `return min(header_seconds, self._backoff_cap)`, где `_backoff_cap = hot.get("models.llm_retry_backoff_cap", settings.LLM_RETRY_BACKOFF_CAP)`, дефолт **8.0 c** (`settings.py:410`). Ровно анти-пример владельца §9: `min(30, 8) = 8`. Фактические сны в логах 1.2–3.9 с (generic backoff `min(1.0·2^n, 8) + U(0,2)`) — Gemini в 429-ответах обычно не отдаёт Retry-After, поэтому реальный эффект: без паузы вообще + бомбёжка fallback-ключей той же группы через ~1–3 с.

### Q5. Какие workers одновременно используют embedding endpoint?

**Факт:** один процесс (`bot.py`), но несколько независимых контуров внутри:
1. `graphrag_rebuild` (task_jobs `kind=graphrag_rebuild`, оба index — P3);
2. live write-путь: `summary_memory._save_graph_fact_embedding` (:2868, traceback выше) — новая graph-fact эмбеддинг (P1);
3. SmartModule/память: `summary_memory._embed_api` (batch ingestion smart_archive/history, `:3889-4008`);
4. потребители retrieval: query-embed при vector-поиске (P0), dossier/episode-jobs (mca-04b/05) через тот же `MemoryManager._embed`.

Multi-**process** координации сейчас нет (один сервис), но два rebuild-джоба запускаются одновременно (см. Q6) и живут в одном event-loop с live-путём — process-local лимитов на embedding нет вовсе (ни семафора, ни rate-limiter), единственный «тормоз» — `GRAPHRAG_REBUILD_SLEEP_SECONDS=0.5` между батчами.

### Q6. Могут ли smart_archive и graph_facts_vec rebuild идти одновременно?

**ДА — и создаются одновременно.** Оба `task_jobs.kind='graphrag_rebuild'` созданы в одну и ту же секунду `created_at=1790807059` (2026-09-30 22:24:19 UTC, старт первого цикла 2.58.40; ADR-1028-5 прод-валидация: «2 джобы засchedule'ены на старте»). Coalesce-key разные (`graphrag_rebuild:smart_archive:<fp>` / `:graph_facts_vec:<fp>`) → TaskSupervisor не имеет контракта взаимного исключения по embedding-квоте; общего embedding-лимитера/lease нет (единственный тормоз — `GRAPHRAG_REBUILD_SLEEP_SECONDS`), поэтому квота-рейс §23 возможен по построению: два rebuild + live-путь делят одну квоту без координации. (Строгость параллельного исполнения — точка верификации Builder'а T-4407; отсутствие **общего** лимитера подтверждено кодом.)

### Q7. Реальный batch size / token load при 429-инциденте?

**Факт (код):** rebuild-батч = `GRAPHRAG_REBUILD_BATCH` **50 фактов на один `_embed()` HTTP-вызов** (`graphrag_rebuild.py:116-121`), пауза `GRAPHRAG_REBUILD_SLEEP_SECONDS=0.5` с (`:124-130`) → теоретически до ~2 вызовов/с ≈ 100–120 embedding-запросов/мин только от одного rebuild. Каждый item ≤ 2048 token (модель), фактические факты — сотни токенов → батч ~10–30k TPM demand. Против этого free-tier Gemini (RPM embedding ≈ 100, TPM/RPD ниже) — перманентный 429.

**Факт (прогресс):** shadow `graph_facts_vec_g1` успел **5450/15277 фактов** (35.7%, `graph_facts_vec_g1_rowids=5450`, `graph_facts=15277`), cursor последнего батча `{"last_id": 6662, "processed": 5450}` — после чего джоба получила 429-каскад и упала. Live-шторм 19:26 — одиночные запросы, и те ловили 429 → к моменту шторма дневная/минутная квота проекта была исчерпана самим rebuild + повторами.

### Q8. Какой Gemini tier/quota виден?

**Факт:** квотные заголовки/JSON-причина Gemini в журнал не пишутся (логируется только `status=429`). Tier напрямую не читаем. Косвенные доказательства free tier: (1) перманентные 429 при ~100–120 RPM-спросе (выше free-tier 100 RPM embedding); (2) 429 даже на одиночных live-вызовах после минут работы rebuild → исчерпание минутного окна/дневного лимита; (3) ADR-1028-5 (прод-валидация 2.58.40) уже квалифицировал: «темп ограничен 429 **free-tier** Gemini». **Ответ:** free tier (вывод), точные RPM/TPM/RPD проекта из прода не извлекаются — контроль должен идти по наблюдаемому поведению (429-классификация), а не по заявленному тарифу.

### Q9. Sync batch / async Batch API / throttled current — что для full rebuild?

**Решение (детали в spec.md A.7):** для P3 full rebuild — **throttled sync `batchEmbedContents` (OpenAI-compat `/embeddings` с batch=50) под управлением adaptive scheduler** как база (уже работает,proof: 5450 фактов собраны), плюс **async Batch API как gated-опция** (env-kill-switch, отдельная quota-группа) для дальнейшей скорости, но НЕ для latency-sensitive P0/P1. Async-путь в ASAP-4 включается только если live-проверка контракта Batch API пройдёт (§16: оцениваются оба механизма — оценили: sync обязателен, async опционален).

### Q10. Почему smart_archive получил `knn_smoke_failed`?

**Факт (БД):** источник пуст: `smart_archive_facts = 0 строк`; main-index shadow-чанки `smart_archive_vector_chunks00/01 = 0 строк`; джоба:

```json
{"job_id": "168adb23…", "kind": "graphrag_rebuild", "coalesce_key": "graphrag_rebuild:smart_archive:96f8…",
 "status": "failed", "reason_code": "knn_smoke_failed", "result_ref": "0",
 "checkpoint_ref": "cp:smart_archive:1:reset",
 "created_at": 1790807059, "updated_at": 1790871720, "finished_at": 1790871720,
 "payload.cursor": {"last_id": 0, "processed": 0}}
```

(1790871720 = 2026-10-01 16:22:00 UTC.) Build не обработал **ни одного** факта (processed=0), smoke прогнали на пустом индексе → 0 KNN-результатов → generic fail. Диагностики (source_count/vector_count/dim/stage) в reason нет — ровно проблема §28. **Ответ:** KNN smoke упал не на векторах, а на **пустом source-множестве** (нет смарт-архивных фактов для этого chat-набора), плюс причина не диагностируема из-за отсутствия reason codes. Требуемый fix: distinct reason `knn_source_empty` + pre-check source coverage до embed-стадии.

### Q11. Что мешает обоим generations перейти building → active?

**Факт (реестр, `mca_embedding_index_generations`):**

| generation_id | index | generation | status | created_at | activated_at |
|---|---|---|---|---|---|
| 1 | smart_archive | 1 | **building** | 1790678362 (29.09 10:39:22 UTC) | NULL |
| 2 | graph_facts_vec | 1 | **building** | 1790678362 | NULL |

fingerprint у обоих `96f80838f683e1cb…4337d` = current (`gen_fp == new_fp` в логах), model `gemini-embedding-001`, dims 3072, preprocessing `casefold-strip-v1`, endpoint_fp `e42d6fd4c65855c2`. Блокеры по цепочке:
1. **graph_facts_vec:** rebuild-джоба `7ed322e6…` status=failed `reason_code=LLMRateLimitError`, result_ref=5450 (2026-10-01 16:22:28 UTC), checkpoint `cp:graph_facts_vec:1` сохранён — 429 → честный terminal `failed` (политика ADR-1028-5 D2, теперь признана неверной для quota-pressure, см. ADR-1028-7 AM-1). resume-with-checkpoint после рестарта запускает build заново → снова упирается в 429 → цикл.
2. **smart_archive:** `knn_smoke_failed` на пустом source (Q10) + собственный 429-цикл.
3. Общие: 21-кратный amplification (Q2/Q3), отсутствие quota-group cooldown (Q1/Q4), параллельный рейс двух rebuild (Q6), live-трафик без приоритета (Q5).

То есть до ACTIVE не дают **не модель и не схема**, а управление quota/retry/retry-политикой — ровно зона A.

### Q12. Какой style_id/revision был выбран в incident Summary run?

**Факт:** incident run `acefcb9989d74571b7caa8e3a65eafdd` (manual, chat `-1002661910336`, SUMMARY_START 01.10 10:22:23 UTC): **`style_id=medved_press, style_revision=1`** — из `COVER_STYLE_START | style_id=medved_press | style_revision=1 | status=start` (01.10 10:29:50 UTC). То же на двух последующих scheduled runs `b1acbc39…` (13:04:43) и `67163d8e…` (19:05:18) — выбор стабильно резолвится (персистенция хотфикса 2.58.43 работает).

### Q13. Был ли event `COVER_STYLE_START` у этого run_id?

**ДА.** `mca_events`: `mca_event=COVER_STYLE_START | ts=1790850590 | pipeline_run_id=acefcb9989d74571b7caa8e3a65eafdd | pipeline_type=summary.cover | job_id=cov_fc92806f35abee6cdb257d44`. Полная цепочка на 3 runs (счётчики mca_events с 29.09): `COVER_PIPELINE_START=6, COVER_BASE_SUCCEEDED=6, COVER_STYLE_START=3, COVER_STYLE_SUBMITTED=3, COVER_STYLE_FAILED=3, COVER_RICH_PUBLISH_SUCCEEDED=6, COVER_PIPELINE_DONE=6`.

### Q14/Q15. На каком условии пропущен/упал Style stage; точный failure reason/provider/model/references?

**Style stage НЕ пропускался — он упал.** Хронология каждого из 3 runs (пример run acefcb99):

```text
10:29:50.476 COVER_STYLE_START    | style_id=medved_press | style_revision=1
10:29:50.530 COVER_STYLE_SUBMITTED| prompt_len=1257 | prompt_hash=df154dc99d1295f1 | reference_count=1 | issue_number=1
10:29:50.550 COVER_STYLE_FAILED   | reason=not_configured | fallback=style_failed | issue_number=1 | duration_ms=72
```

**Ответ:** `reason=not_configured` — выход из `cover_style_edit.edit_image` (`services/cover_style_edit.py:211-213`: `if not base_url or not model → EditResult(ok=False, reason="not_configured")`) — для **edit-операции не сконфигурировано connection/model** (owner-гейт DC-4 из conflict-audit §9: edit-capable connection не настроен). Это конфигурационный отказ за 72 мс — **реальный image-edit API-вызов не делался ни разу**; reference (`reference_count=1`, medved_press.png) в edit-request не уходил, provider/model у события пустые. Base cover при этом успешно генерировался (`BASE_SUCCEEDED`, provider `nanogpt`, model `qwen-image-3-pro`) и публиковался (`RICH_PUBLISH_SUCCEEDED`) — поэтому пользователь видел base-обложку без стиля. Дефект зоны B не в «style потерялся», а в: (а) отсутствие diagnostic-события/видимой причины для владельца до сегодняшнего разбора; (б) `COVER_STYLE_FAILED.reason_code=style_failed` в mca_events схлопывает конкретную причину (`not_configured`) в generic-код; (в) issue_counter увеличивался (1→2→3) на фейлах — расход нумерации на неуспешные style-попытки.

### Q16. Проходит ли selected style через Level-3 Legacy fallback?

**ДА — уже проходит.** Run `b1acbc39…` (13:00 scheduled): `L2_ERROR invalid_paragraph — LEVEL-3 legacy fallback` (13:03:02) → `LEGACY_FALLBACK reason=l2_unusable` → `COVER_STYLE_START medved_press` (13:04:43) → тот же `not_configured`. То есть единый cover-pipeline после Legacy формально вызывается; проблема инцидента — не обход Style, а его конфигурационный фейл + слабая видимость. Regression-тест §39 (`style selected → Legacy → style stage invoked`) подтверждает существующий контракт и остаётся обязательным, чтобы не деградировал.

### Q17. Почему L1 получил `too_many_facts` на incident run?

**Факт (лог):**

```text
10:27:41 L1 invalid response | run_id=acefcb99… | reason=too_many_facts
10:27:41 L1_COMPLETE | provider=nano-gpt.com | model=deepseek/deepseek-v4.1-flash | tokens_in=46118 | tokens_out=14351
        | threads=0 | facts=0 | chunks=1 | attempts=1 | status=invalid | invalid_reason=too_many_facts | duration_ms=29615
10:27:41 L1_FALLBACK_PACKAGE | reason=too_many_facts | fragments=30 | chronology=688
```

**Факт (код):** `services/summary_l1_contract.py:62-63` `MAX_FACTS_PER_THREAD = 30`, `MAX_FACTS_TOTAL = 1000`; `:409-410` — `len(facts_raw) > MAX_FACTS_PER_THREAD → invalid_result(REASON_TOO_MANY_FACTS)` на **весь** L1-ответ. Окно 688 сообщений ушло **одним chunk'ом** (`chunks=1`), модель на плотном 6-часовом окне закономерно нашла >30 фактов в одном треде → весь L1 объявлен invalid → деградация до emergency fallback-пакета (30 fragments + chronology, без semantic topics/attribution anchors). Никакого sharding'а до валидации не выполнялось (chunks=1 при токенах, позволявших разрез по §52). Это ровно сценарий §51/§50.36: capacity-гард превратился в semantic guillotine.

**Дополнительные прод-факты по Summary-контуру (контекст для зоны C/D):**
- `L1_FALLBACK_PACKAGE` за 29.09–01.10: 5 случаев, из них 4 × `reason=llm_timeout` (29.09 01:03 fragments=30 chronology=369; 29.09 13:07 chronology=686; 29.09 19:09 fragments=0 chronology=0; 30.09 13:08 chronology=921; 30.09 19:06 chronology=477) и 1 × `too_many_facts` (Q17) — то есть L1-LLM (deepseek-v4.1-flash через nano-gpt) систематически тайм-аутит на больших окнах (attempts=3, ~155 c).
- `XML context: hard cap 50000 chars reached, stopping at …` — 4 случая: 30.09 01:02 (330 msg), 30.09 19:08 (318 msg), 01.10 10:27:47 (**307/688**), 01.10 13:03 (307 msg). Источник: `services/summary_xml.py:72-79` — цикл обрезает `chat_history` по `limits.summary_max_context_chars` (50000) **без чанкования/reduction** — Legacy теряет ~55% окна молча.
- `L2_ERROR → LEVEL-3 legacy fallback`: причины на проде: `invalid_paragraph` (30.09 01:02; 01.10 13:03), `llm_timeout` (30.09 07:05; 30.09 19:08), `quote_attribution` (29.09 19:11 run 8120c190…; 01.10 10:27 run acefcb99…). Примечательно: в обоих quote-фейлах `quote_unverified=0` — отвергались **найденные в пуле** цитаты из-за именной атрибуции (см. Q27).
- Стирание истории: `services/summary_generator.py:840-841` — после успешной публикации `if ctx.status in (DEGRADED, FAILED): ctx.status = STATUS_OK` — подтверждено кодом (Q36).

### Сводная таблица Q1–Q17

| Q | Ответ (сжато) |
|---|---|
| Q1 | 3 credential, 1 endpoint; точно не 3 независимых группы; вероятно 2 (fallback#2 — «запасной аккаунт» по коду); machine-доказательства нет → default 1 группа + developer-label |
| Q2 | До 21 HTTP-вызова: 3 × (3 + 2 + 2) |
| Q3 | Да, amplification жив (лог 01.10 19:26–19:27, код summary_memory:282 + llm_client:371/1317-1362) |
| Q4 | Нет: `min(Retry-After, 8.0)` — llm_client.py:661, cap=settings:410 |
| Q5 | 1 процесс; 4+ контура: rebuild×2, live write, batch ingestion, query-embed |
| Q6 | Да: оба job созданы в одну секунду 1790807059, параллельно |
| Q7 | Батч 50 фактов/вызов, sleep 0.5с → ~100–120 RPM demand; прогресс 5450/15277 до 429 |
| Q8 | Free tier (вывод из 429-паттерна + ADR-1028-5); точные квоты из логов не извлекаемы |
| Q9 | База: throttled sync batch (есть proof); async Batch API — gated-опция для P3 |
| Q10 | KNN smoke на пустом source (`smart_archive_facts=0`, processed=0) + отсутствие reason codes |
| Q11 | Блокеры: 429→terminal failed (policy), knn_smoke generic, amplification, нет cooldown, рейс rebuild'ов |
| Q12 | medved_press, revision=1 (все 3 runs) |
| Q13 | Да, COVER_STYLE_START есть (3/3 runs) |
| Q14 | Stage не пропущен — упал: `not_configured` (нет edit connection/model), 72 мс, API не вызывался |
| Q15 | provider/model пустые; reference_count=1 (не уходил); base = nanogpt/qwen-image-3-pro |
| Q16 | Да, Legacy-путь вызывает тот же style-pipeline (run b1acbc39) |
| Q17 | MAX_FACTS_PER_THREAD=30 гильотинит весь L1 при chunks=1 на окне 688 → fallback-пакет |

---

## Часть II. Q18–Q37 — решения по коду/дизайну

(Нумерация разделов A.x/C.x/D.x/E.x соответствует `spec.md`; детальные контракты там.)

### Q18. Что именно означал L2 `quote_attribution` на incident run?

На проде `L2_COMPLETE status=invalid invalid_reason=quote_attribution` при **`quote_unverified=0`** (оба случая: 29.09 19:11, 01.10 10:27) — значит отвергалась цитата, **найденная** в пуле пакета, исключительно из-за наличия именной атрибуции рядом. Т.е. `quote_attribution` в текущем коде — не «цитата не найдена» и не «типографика», а отказ класса §50.20 (named-attribution → reject всегда). Спектр реальных подпричин (не найден текст / спикер не доказан / именной reject) схлопнут в один код — см. Q21.

### Q19. Почему Legacy режет XML на 50k/307 после full-window contracts?

Full-window contracts (ASAP-3.1/3.2) покрывают **Hybrid-контур** (L1 chunking, semantic reduction FactPackage). Legacy-контур продолжает собирать плоский `<chat_history>` через `XmlGroundingBuilder.build` (`summary_xml.py:54-85`), который молча останавливается по `limits.summary_max_context_chars=50000` — contracts туда просто не проведены. Это не «порча контракта», а непокрытая ветка: аварийный путь был написан до contracts и не был включён в их периметр.

### Q20. Минимальная архитектурная правка, закрывающая три Summary regression без второго pipeline

Одна связка в существующем `summary_generator` (зоны C+D, без нового контура):
1. **L1:** caps 30/1000 → capacity guards: pre-emption (semantic sharding/`chunks>1` при planning-оценке §52) + deterministic reduction до cap вместо invalid (spec C.1).
2. **Quote:** 5 reason codes + local repair pipeline (paraphrase/de-quote/атрибуция по evidence) + revalidate до объявления unusable (spec C.2).
3. **Legacy:** XML 50k-cap → full-window путь (reuse `summary_semantic_reduction` поверх полного окна / chunked Legacy) + coverage-metric обязателен (spec C.3).
Все три — точечные замены в уже существующих стадиях; второго pipeline нет; OFF-kill-switch возвращает бит-в-бит текущее поведение.

### Q21. Текущий `quote_attribution`-валидатор: типографика или семантика? Какие подпричины схлопнуты?

Код (`summary_l2_writer.py:722-731`): для каждой кавычки в тексте — (1) substring-lookup нормализованного текста в пуле пакета (`_quote_matches_pool`); (2) эвристика `_has_named_attribution` (имя рядом с кавычкой). Матрица: не найдена + имя → **reject**; не найдена без имени → молча снять кавычки; **найдена + имя → reject** (баг §50.20 — прод-кейс Q18); найдена без имени → ok. Speaker/source **никак не резолвятся** — «семантика» ограничена substring+именем. Типографская нормализация кавычек — отдельно (`cleanup_llm_text`, ASAP-2.1) и к reject'ам не приводит. Схлопнутые подпричины: `quote_text_not_found` (при имени), `named_quote_class_reject` (найдена+имя), потенциальный `quote_speaker_unresolved` — всё в один `quote_attribution`. Новый контракт — 5 кодов §53.1 (spec C.2).

### Q22. Можно ли repairable quote failure чинить локально без Legacy?

Да, и это не новая механика: ветка «не найдена без имени → снять кавычки» уже существует локально (тот же цикл). Расширение: детерминированный repair-set §53.2 (de-quote → paraphrase-маркировка, drop speaker-name, сохранить событие) + revalidate; LLM-вызов НЕ нужен для большинства случаев (paraphrase формулировки может потребовать Revision-вызова — это уже bounded revision loop зоны D). Запрещено: invent speaker/text. Legacy — только после 2 revision-итераций с blocking findings.

### Q23. Какие structured stage events уже есть и чего не хватает?

Есть: `summary_run_log` текстовые события (SUMMARY_START/DONE, L1_COMPLETE/L1_FALLBACK_PACKAGE, L2_START/COMPLETE/ERROR, LEGACY_FALLBACK, XML-cap warning) + зеркала в `mca_events` (COVER_PIPELINE_*, COVER_BASE_SUCCEEDED, COVER_STYLE_START/SUBMITTED/FAILED, COVER_RICH_PUBLISH_SUCCEEDED — с `pipeline_run_id/pipeline_type/job_id`), `task_jobs` (embedding/cover/media job state с checkpoint), `mca_pipeline_runs`. Не хватает: единой **stage-модели** (строка на стадию со status/reason_code/latency/counts/provider/attempts/fallback_from→to), поля `source_coverage` как first-class, разделения repair/fallback/failure, embedding-стадий (paused_rate_limit и др.), человекочитаемых reason-переводов. Ответ: расширить `mca_events.py:REASON_CODES` + ввести normalized stage record поверх `mca_pipeline_runs` (spec E.1), не создавая второй store (§61.11/§61.12).

### Q24. Единый stage/event schema для Last Run и агрегатов

Один normalized record (§61.11-набор) пишется **тем же кодом**, что и human-log: `run_id, stage, attempt, status(ok|repaired|fallback|failed|skipped|running), reason_code, reason_detail_safe, started_at, finished_at, latency_ms, input_count, output_count, coverage, provider, model, attempts, fallback_from, fallback_to` + typed extension cover-fields. Last Run = проекция по run_id; 24h/7d = агрегаты по тем же записям. Существующие точечные события (COVER_*, L1_*) маппятся на stage-модель адаптером; дублей событий не вводим.

### Q25. Как вычислять run health

`publication_status ∈ {published, degraded_publication, failed}` × `source_coverage ∈ [0..1]` → `pipeline_health ∈ {healthy, repaired, degraded, failed}` (матрица §61.6): published+coverage<1 = **degraded** (не healthy), repair-этапы не ухудшают health, fallback понижает до degraded, failure — failed. Числового score нет (§61.13) — только badge + явные оси.

### Q26. Почему prompt запрещает цитаты и какая миграция нужна

Канон ASAP-2 («Прямые цитаты не приводи…») был защитой от transcript-стены цитат без proof-механизма: тогда не было ни reviewer, ни evidence-трассировки, ни repaired quote-валидатора — запрет был дешёвым эквивалентом safety. Владелец отменил (§50.3). Миграция (spec D.1): удалить запрет из активного промпта эталона; добавить prose-first narrative-правила (косвенная речь — default; цитата редкая/выразительная/доказанная; modality сохранять; стиль бота сохранять; style-комментарий ≠ новый факт). Меняются код+эталон+тесты одним коммитом; old prompt не rollback-target (OFF-паритет = прежнему текстовому поведению отвечает только Legacy-промпт, который не трогаем).

### Q27. Почему validator отклоняет named attribution при найденной цитате

Историческая перестраховка ASAP-2: имя рядом с цитатой считалось маркером «модель приписала реплику по соседству» (speaker-proof отсутствует) → banned как класс. Цена видна на проде (Q18): качественная статья валилась в Legacy из-за одной цитаты. Новый контракт (spec C.2/D.2): найденная+доказанная (evidence ref от reviewer/пакета) named quote = **valid**; найденная+недоказанная = needs_fix (repair: снять имя, не текст); не найденная = paraphrase/de-quote. Имя как класс не запрещается никогда.

### Q28. Internal evidence trace для paragraph/claim

**Реюз существующих FactPackage `evidence_message_ids`** (стабильные message-id из id_space — уже валидируются `summary_l1_contract`): paragraph получает `evidence_message_ids[]`, inventor ref → validation error (id_space-проверка уже есть — переиспользуем), refs не публикуются (internal metadata). Нового ID-пространства не заводим; fact-refs можно добавить позже без schema-разрыва (список гетерогенных ref-ов допустим). Обоснование: message-id — единственный ID, который уже доказуемо существует во всех стадиях (source→L1→package) и уже проверяется кодом.

### Q29. Reviewer без права создавать истину

Контракт: reviewer получает FactPackage+roster+deterministic findings и возвращает **только** `{status: approved|needs_fixes|unusable, findings[]}`, где каждый finding обязан иметь `evidence_refs ⊆ package refs` (или класс deterministic-rule) — иначе finding отбрасывается как invalid. Допустимые вердикты по спикеру: подтверждён/не подтверждён/противоречие/неоднозначность/claim не найден в evidence. «Наверное Вася» — запрещено; unknown > hallucination. Инструкции repair — свободный текст, но без новых фактов (проверка: repair-инструкция не содержит чисел/имён, отсутствующих в package — deterministic guard на пост-обработке findings).

### Q30. Paragraph patch vs full rewrite — выбор

**Выбор: paragraph-level replacement patch** (`{"replace_paragraphs":[{index,text,evidence_refs}]}`) как основной контракт Revision, с детерминированным fallback на full-document revision в двух случаях: (а) findings покрывают >50% абзацев; (b) патч дважды не прошёл валидацию (несуществующий index/структура). Обоснование: (1) §50.2 «сломалась плитка — не сносим дом» — patch минимизирует риск «починил цитату → сломал три факта», т.к. нетронутые абзацы байт-в-байт сохраняются и повторно НЕ валидируются semantic-reviewer'ом (только затронутые); (2) детерминируемость: diff/валидация патча механическая; (3) токен-бюджет предсказуем; (4) full-rewrite остаётся как escape-hatch, иначе pathological cases (массовая перестановка хронологии) упирались бы в искусственное ограничение. Preserve-инструкция и regression-тесты §50.22/50.63 обязательны для обеих веток.

### Q31. Bounded call budget

| Путь | L1 | Writer | DetValidator | Reviewer | Revision | Итого LLM (logical) |
|---|---|---|---|---|---|---|
| Happy | k | 1 | 0 | 1 | 0 | k + 2 |
| Revision #1 | k | 1 | 0 | 1+1 | 1 | k + 4 |
| Revision #2 | k | 1 | 0 | 1+1+1 | 2 | k + 6 |
| Legacy после loop | k | израсходовано выше | — | — | — | k + 6 + L |
| Legacy прямой (writer runtime fail) | k | 1 | 0 | 0 | 0 | k + 1 + L |

k = число L1-чанков (planning §52), L = число Legacy-частей (≤ MAX_SUMMARY_PARTS, не трогаем). Жёсткий потолок L2-стадии: **≤ 6 LLM-вызовов** (writer+reviewer+revision). Provider retry/fallback (transport) в budget не входит — это не логические вызовы; review_degraded (§50.29) НЕ добавляет вызовов. Нового 10–15-call каскада нет: максимум зафиксирован и тестируется (golden J/M).

### Q32. Текущие FactPackage reductions, теряющие topics/attribution anchors

1. `too_many_facts`-гильотина (Q17) — теряет **всё** semantic content → 30 fragments + chronology (без topics/attribution/anchors).
2. Позиционные каскады `_apply_fragment_caps`/`_enforce_budget` (ADR-1028-5 D8) — «старые первыми» по timestamp, уже переведены в fail-soft последней линии, но остаются.
3. XML 50k-cap Legacy (Q19) — теряет ~55% сообщений.
4. `L1_FALLBACK_PACKAGE` с fragments=0/chronology=0 (29.09 19:09) — полностью пустой пакет возможен (пойман guard'ом).
5. Отсутствие roster/relation-полей в пакете (Q35) — anchors теряются не «ножницами», а никогда не записываются.
Контракт fix — spec C.1/D.6: hierarchical reduction через `summary_semantic_reduction` + coverage map §50.32 обязательна.

### Q33. Как доказать 100% source-considered coverage при 600–700+ сообщений, не превращая статью в transcript

Coverage определяется на **considered**, не на «скопировано»: (1) planning делит окно на chunks по semantic cardinality (§52), все сообщения распределены по chunks; (2) каждая chunk-строка считается рассмотренной, если её id ∈ `source_messages_considered` пакета (L1 output + unassigned + repair-учёт); (3) merge сохраняет many-to-many membership; (4) статья — выжимка: покрытие тем (major topics map §50.16) + evidence-полного окна, а не копия сообщений; (5) coverage-число публикуется как first-class (§61.6) и считается детерминированно (id-множества), не эвристикой. Transcript-защита — ограничение длины статьи + prose-first промпт + reviewer-код `duplicate_event`/transcript-паттерн (§50.62 acceptance, не validator).

### Q34. Как различать factual claim и допустимый сарказм

Правило для Reviewer: бракуется только стилистическая фраза, которая создаёт **проверяемое событие/утверждение**, отсутствующее в evidence. Operational-критерий (§50.26 + §50.13): (а) модальность — гипербола/ирония без конкретного actor+action+time → style; (б) появление конкретного места/времени/действия/числа, которых нет в evidence → factual_overstatement (найти: «уехал в Москву» при отсутствии в пакете); (в) финальный guard — finding обязан иметь evidence_refs, «мне кажется это факт» без ref = invalid finding. Промпт Writer получает правило §50.6 (видимая действительность vs авторская интерпретация) — это снижает частоту, deterministic+reviewer ловят остаток.

### Q35. Какие reply/forward/quote metadata есть в payload, а какие теряются до L2

Есть и доезжают: `reply_to_id` в source-строках и XML-контуре (маркер ответа), `author_id/author_name` в окне и fact-evidence (message-id anchors), trigger-маркер. Теряется до L2: **forward-происхождение** (в `summary_l1_clusterizer`/`summary_fact_package` forward-полей нет — grep подтверждает отсутствие обработки), **quoted-text ≠ слова quoting-user** (нет различения), subject-of-statement (не решается до MCA-22-стека — и не должно, reuse существующего identity закрыт conflict-audit §6). Fix в scope ASAP-4: реляционные теги (`kind: msg|reply|forward|quote`) в FactPackage fragment'ах + правило §50.9/§50.40 в промпт/validator; глобальный identity stack не строим.

### Q36. Где run context стирает intermediate state и как сохранить immutable stage history

Точка стирания подтверждена: `services/summary_generator.py:840-841` — после успешной публикации Legacy `ctx.status` из DEGRADED/FAILED перезаписывается в `STATUS_OK` (удобно для delivery, уничтожает историю). Fix (spec E.1/D.7): разделить `publication_status` (delivery-результат) и `pipeline_health` (агрегат стадий); каждая стадия пишет append-only stage-event (Q24-схема), финальный run-record агрегирует, но не переписывает; `ctx.status` остаётся delivery-полем, на health больше не влияет. Regression: успешный Legacy run обязан показывать `L2 rejected → Legacy used` в Run Inspector.

### Q37. Какие delivery failures сейчас могут ошибочно отправить текст в Legacy

Прямой路由 publish-fail → Legacy в коде нет (ladder: Rich fail → plain; `summary_generator.py` не вызывает `_legacy_fallback` из delivery-ветки). Реальный риск — другой: **formatting/validation-класс причин L2** отправляет хороший текст в Legacy: `invalid_paragraph` (2 прод-кейса) и `quote_attribution` (2 кейса) — это presentation/repairable-причины, а не семантическая непригодность. §50.48/§50.19/§50.20+C.2 закрывают: emphasis/formatting repair — локально без LLM, quote repair — до unusable; Legacy остаётся только для: непригодный FactPackage, blocking findings после ×2 revision, writer/provider runtime-fail. Плюс guard: после formatter-фейла запрещено дёргать Legacy (approved prose сохраняется, plain-formatter ladder §50.49) — фиксируется тестом (golden D + §50.49 regression).

---

## Приложение: воспроизводимость выборки

- Журнал: `journalctl -u admin_bot --since '2026-09-29' | grep -E 'EMBEDDING|embed|429|COVER_STYLE|L1_|L2_|LEGACY_FALLBACK|XML context'`
- DB (read-only): таблицы `mca_embedding_index_generations`, `task_jobs`, счётчики `graph_facts`, `graph_facts_vec_g1_rowids`, `smart_archive_facts`, `mca_events` (GROUP BY event_name).
- Env: только имена переменных (`grep -oE`), значения ключей не раскрывались нигде, включая этот документ.
- Все epoch-таймстампы конвертированы в UTC (журнал сервера идёт в UTC).
