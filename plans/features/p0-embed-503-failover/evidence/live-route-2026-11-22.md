# Live route check — 2026-11-22 (UTC 2026-11-21)

P0 `p0-embed-503-failover`, срез `E503-ROUTE-PROBE`. Read-only проверка production:
без записи в `.env`/settings/keys/DB/индексы, без рестарта и без вызова recovery/backfill.
Машинный дубль: `live-route-2026-11-22.json`.

## 1. Проверенная identity

| Поле | Факт |
|---|---|
| Host | `vps159032-gqg` |
| Deployed SHA | `374dc60609986a9250170a34a48c93bf2ba85e29` (2.58.228) |
| Unit / MainPID | `admin_bot` / `2944369` |
| Process start | `2026-11-21T10:56:31Z` |
| Проверка | `2026-11-21T14:29:58Z` — `14:34:03Z` |
| Effective config | process environ + `config.settings` + `bot_settings` (PG read-only) |
| Control plane | `EMBED_CONTROL_PLANE_ENABLED=true` (default ON), cooldown/priority/adaptive ON, async batch OFF |
| Hot-конфиг | все `models.embedding*`/`keys.embedding*` строки обновлены **до** старта процесса; snapshot PG совпадает с загруженным при старте |
| Ключи | primary/fallback_1/fallback_2 — present, source=`hot`; значения различны (`primary≠fb1≠fb2`) |

Профили (host/path без query и секретов):

| Alias | Host + path | Model | Quota group | PCI |
|---|---|---|---|---|
| `primary` | `apinet.cloud` `/v1` | `gemini-embedding-001` | `apinet_paid` (explicit) | `a93485483697c3c3` |
| `fallback_1` | `generativelanguage.googleapis.com` `/v1beta/openai` | `gemini-embedding-001` | `google_free_1` (explicit) | `6b7e0a69d0bf080d` |
| `fallback_2` | `generativelanguage.googleapis.com` `/v1beta/openai` | `gemini-embedding-001` | `google_free_2` (explicit) | `63488c34c6e08127` |

## 2. Реальные POST /embeddings

Метод: deployed `services.llm_client.LLMClient.embed_once`, по одному POST на профиль,
нейтральный ASCII-текст, timeout 30 s, `max_retries=0`, `retry_statuses=()`, без повторов.
`request-id` недоступен: `embed_once` не отдаёт заголовки ответа.

| Alias | UTC | HTTP | Класс | Vector | L2 | MSI | Latency |
|---|---|---:|---|---:|---:|---|---:|
| `primary` | `14:29:58.153Z` | **503** | `LLMServerError` | — | — | — | 1649 ms |
| `fallback_1` | `14:29:59.802Z` | **200** | — | 3072 | 1.0 | `e540d4ad890e121d` | 311 ms |
| `fallback_2` | `14:30:00.154Z` | **200** | — | 3072 | 1.0 | `e540d4ad890e121d` | 289 ms |

Cosine на одном и том же тексте: `fallback_1~fallback_2 = 1.0`. Primary-вектора нет
(503), поэтому primary↔Google cosine в этом прогоне не измерен.

## 3. Какой alias/endpoint реально вызывался при 503

Это **`primary` → `https://apinet.cloud/v1/embeddings`**, модель `gemini-embedding-001`,
ключ из hot-конфига, quota group `apinet_paid`.

Доказательства:

1. Live probe: primary вернул 503 за 1.6 s; оба Google-слота в тот же момент вернули 200.
2. Deployed `services/embedding_control_plane.py` (`374dc6060`):
   `_pick_credential()` берёт **первый healthy** credential, у которого группа не blocked;
   transport 5xx/timeout в `_on_error()` возвращает `"transport"` и **намеренно не меняет**
   health credential/группы («retry того же logical request обязан идти по тому же пулу»).
   В цикле `embed()` после transport-ошибки бюджет уменьшается, затем снова вызывается
   `_pick_credential()`; при pool order `primary → fallback_1 → fallback_2` и здоровом primary
   все ≤4 попытки снова уходят в primary.
3. Journal 24 h (UTC `2026-11-20T14:30:02Z` — `2026-11-21T14:29:55Z`):
   - `973` строк `LLMServerError` / `LLM server error`;
   - `844` строк `embed transport error | error=LLMServerError`;
   - `219` строк `EmbeddingRetriesExhausted` (deployed class — subclass of `EmbeddingBudgetExhausted`, `_ATTEMPT_BUDGET=4`);
   - `43` строк, где одновременно `apinet.cloud` и `503`; точный пример:
     `services.llm_client.LLMServerError: LLM server error 503: https://apinet.cloud/v1/embeddings`;
   - `0` строк `embed rate limit`, `0` `embed credential auth_failed`;
   - batch-WARN: `quota_group=unknown | state=EmbeddingRetriesExhausted` — у этого класса нет
     `group_id`, поэтому WARN не печатает alias; это признак исчерпания transport-бюджета,
     а не 429/quota cooldown.
4. `embedding_quota_state`: строки `exhausted` от `2026-10-22` с `next_allowed_at`
   `2026-10-23T00:05Z` (в прошлом). `group_blocked()` сбрасывает такую группу в healthy
   при следующем обращении; в 24 h нет 429. Это не текущий блокирующий фактор.

Итог: исторический 503 шёл в **primary/apinet**, а не в Google. Google-слоты executor
не пытался использовать.

## 4. Google fallback: функциональность и identity

Функциональность доказана: оба слота вернули реальный вектор **3072**, L2-норма **1.0**,
одинаковый MSI `e540d4ad890e121d`, cosine `fallback_1~fallback_2 = 1.0`.

Generation/admission:

| Поле | Значение |
|---|---|
| Active `graph_facts_vec` generation | 1, status `active`, provider `generativelanguage.googleapis.com` |
| Model / dims / preprocessing | `gemini-embedding-001` / 3072 / `casefold-strip-v1` |
| Activated | `2026-10-23T05:53:35Z` |
| MSI generation | `e540d4ad890e121d` |
| Durable admission | space `e540d4ad890e121d`, conn `a93485483697c3c3`, checked 12, mean/min 1.0, hit5 1.0 |
| `resolve_index_compat(graph_facts_vec)` | `compatible`, `ADMITTED_COMPATIBLE`, `serviceable=true`, `needs_probe=false` — для **primary apinet PCI** |

Для Google-слотов:

- `probe_msi == space_now == stored_space` → `true` (identity/размерность совпадают);
- `admission_valid_for_probe = false`, потому что durable admission привязан к PCI
  `a934…` (primary), а Google PCI — `6b7e…`/`6348…`;
- классификация existing gate: `COMPATIBILITY_UNKNOWN`, не `INSTANT/ADMITTED`.

То есть Google-вектор **функционально работает и совпадает с активным MSI/размерностью**,
но formal admission именно для Google PCI не доказан: по действующему гейту нужна
canary/probe/adoption на этом соединении. Активное поколение само зарегистрировано под
provider `generativelanguage.googleapis.com`, а admission `mean=min=1.0` на 12 пробах
привязан к apinet; это полезный исторический факт, но не замена admission для Google PCI.
Смешивать векторы без этого гейта нельзя.

## 5. Text-only backlog и recovery (read-only)

SQLite открыт `mode=ro`, `PRAGMA query_only=ON`, с deployed `sqlite_vec` extension.
Recovery/backfill **не запускался**.

| Метрика | T0 `14:32:09Z` | T1 `14:32:19Z` |
|---|---:|---:|
| `smart_archive_facts` total | 0 | 0 |
| `smart_archive` vec rows | 0 | 0 |
| archive facts без vec | 0 | 0 |
| archive recent (24 h) без vec | 0 | 0 |
| `graph_facts` eligible | 29 212 | 29 212 |
| `graph_facts_vec` rows | 31 704 | 31 704 |
| graph facts без vec (eligible) | **4 463** | **4 463** |
| graph recent (24 h) без vec | **1 187** | **1 187** |

`graph_vec_rows > eligible` потому что в vec-таблице остаются expired-строки; счётчик
missing считает только eligible. За 10 s счётчики не изменились; `embed recovery tick`
в journal за 24 h — **0** строк, поэтому прогресс recovery этим прогоном не подтверждается
и не заявляется.

`mca_events` за 24 h:

- `EMBED_API_DEFERRED` — 31 батч, сумма `facts_text_only = 143`;
- первый `2026-11-20T16:16:53Z`, последний `2026-11-21T14:08:30Z`;
- `EMBED_API_FAILED` — 0: `EmbeddingRetriesExhausted` относится к serviceability-состояниям
  и не эмитится как failed-событие; поэтому 219 journal-строк не дублируются в `mca_events`.

`smart_archive` — отдельное состояние, не 503:

- source rows 0, vec rows 0, active generation нет;
- две `superseded` генерации: gen1 provider Google, gen2 provider apinet, обе MSI `e540…`;
- resolver: `source_empty`; rebuild job: `validation_failed / knn_source_empty`.

## 6. Журнал: точные границы и ограничения

| Параметр | Значение |
|---|---|
| Окно journald | `2026-11-20T14:30:02Z` — `2026-11-21T14:29:55Z` |
| Строк просканировано | 83 113 |
| `503` (любой) | 918 |
| `LLMServerError` | 973 |
| `embed transport error` | 844 |
| `EmbeddingRetriesExhausted` | 219 |
| `text_only` / `embed_deferred` / batch WARN | 169 / 62 / 31 |
| `lexical only` / FTS fallback | 108 |
| `embed rate limit` / auth failed | 0 / 0 |
| `LLM embed fallback` (legacy) | 0 |
| `vec reactivated` / `embed recovery tick` | 0 / 0 |
| `smart_archive superseded` / `knn_source_empty` | 90 / 90 |
| `apinet` / `apinet_503` | 43 / 43 |
| `google host` в логах | 0 |

`918` — все 503 в окне, не только embeddings; `43` — точное пересечение apinet+503.
Последний общий 503 — `14:16:48Z`, последний apinet 503 — `13:53:40Z`; live probe в
`14:29:58Z` снова получил 503. Это текущий внешний отказ apinet, а не только история.

## 7. Сверка с журналом apinet

С production-хоста **нет доступа** к кабинету apinet: нет dashboard-сессии, export,
account id или key id. Поэтому нельзя подтвердить/опровергнуть «0 записей в выбранном
диапазоне», определить пояс кабинета, фильтры и выбранный key/account. Это остаётся
внешним ограничением, а не выводом о балансе/сети.

Что доказано сервером:

- endpoint `https://apinet.cloud/v1/embeddings` доступен и **реально отвечает 503** на
  primary credential (live probe + 43 journal-строки с точным URL);
- это не «нет запросов»: запросы есть, шлюз отвечает 503.

Что не доказано: причина пустого выбора в кабинете (timezone/фильтры/key/account),
баланс и upstream. Формулировка «apinet починен» запрещена — он не починен.

## 8. Итог (1)–(5)

1. **Alias/endpoint при 503:** `primary` → `https://apinet.cloud/v1/embeddings`,
   `gemini-embedding-001`, quota group `apinet_paid`. Причина повторения — transport-ошибка
   не исключает endpoint, `_pick_credential` снова выбирает primary.
2. **Google fallback:** функционально работает (оба слота 200, 3072, norm 1.0, MSI
   `e540d4ad890e121d`, cosine 1.0). Совместимость с active MSI/размерностью — да;
   formal admission для Google PCI — **не доказан** (admission привязан к apinet PCI,
   gate даёт `COMPATIBILITY_UNKNOWN`); нужен существующий canary/probe на Google PCI.
3. **Text-only backlog:** archive 0/0; graph missing **4 463**, recent 24 h **1 187**;
   `EMBED_API_DEFERRED` 31 батч / 143 новых text-only. T0=T1 за 10 s; recovery не
   запускался, `embed recovery tick` в журнале 0.
4. **Журнал:** 24 h, 83 113 строк, 918×503, 973×LLMServerError, 844×transport error,
   219×EmbeddingRetriesExhausted, 0×429/401, 43×apinet+503, 0×Google host. Пустой журнал
   apinet кабинета не объяснён; доказан только реальный 503 от шлюза.
5. **Открытые внешние ограничения:** apinet 503 остаётся; кабинет apinet (timezone,
   filters, key/account) недоступен; request-id не отдаётся deployed `embed_once`;
   formal Google-PCI admission требует отдельного canary/probe; primary-вектор для
   cross-provider cosine отсутствует из-за 503.

Safety: записей/рестартов/изменений конфигурации/БД/индексов нет; PostgreSQL — READ ONLY,
SQLite — `mode=ro`/`query_only`; recovery не вызывался; temp-скрипты удалены; фоновых
процессов не оставлено.
