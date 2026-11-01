# EVOL-SRC-READER — контракт проверенного чтения исходников (архитектурное решение)

Источник требования: `plans/current_task.md` §1 (строки 1176–1236). Слайс: `EVOL-SRC-READER` (W6).
Роль: Architect. Статус: решение заморожено для одной Builder-полосы и одного прохода Reviewer.
Ветка при осмотре кода: `evol/impl` @ `49caaf6c`, worktree `…/evol-71536a366a11-c63f6f44`.

## 0. Вердикты по направлениям

| Направление | Вердикт | Основание в коде |
|---|---|---|
| Tool surface | **ARCHITECT_REQUIRED** | канон инструментов `services/tool_schemas.py:848-864` (15 записей) = новый легальный слот 16 |
| Transport/security reuse | **ARCH_REUSE_CONFIRMED** | `services/safe_fetch.py:504-667` (`SafeFetcher.fetch/fetch_json/fetch_text`), SSRF `guarded_target/aguarded_target :330-400`, redirect `:530-577`, лимиты `Profile :401-430`, маскирование `mask_url/mask_text :130-151` |
| Caching/idempotency | **ARCH_REUSE_CONFIRMED** | `source_reuse.store/lookup :368-455`, `read_level_* :48-56`, dedupe одинаковых вызовов `tool_loop._TOOL_MAX_SAME_CALL=2 :52`, `_args_fingerprint` `direct_execution.py:501` |
| Evidence window/budget | **ARCH_REUSE_CONFIRMED** | `tool_router._evidence_window :1369-1400`, `auto_budget.resolve_evidence_tool_window :413-435` (`_kind_defaults :394-398`: неизвестный kind → legacy 8000, floor 0 — правки не нужны) |
| Provider adapter boundary | **ARCHITECT_REQUIRED** | в `services/**` нет ни одного упоминания github/raw/api.github — адаптера нет |
| Follow-up depth/size | **ARCHITECT_REQUIRED** (числа ниже) | аналогов «обхода вызовов» в проекте нет |
| Evidence contract (payload/статусы) | **ARCHITECT_REQUIRED** | `tool_result.classify_output :484-529` знает закрытый набор payload-статусов |
| Телеметрия | **ARCH_REUSE_CONFIRMED** (0 новых кодов) | `mca_events.REASON_CODES :60-350` (прецедент переиспользования `:263-268`), стадийный эмиттер `mca_retrieval_context.emit_stage_event :274-288` |
| Kill-switch | **ARCH_REUSE_CONFIRMED** (env-only прецедент) | `config/settings.py:1431-1436` (`ARTICLE_TOOL_ENABLED`), гейт анонса `tool_schemas._article_tool_enabled :896-902` |
| Capability/evidence policy | **ARCHITECT_REQUIRED** (минимальная проводка) | слот зарезервирован: `evidence_policy.py:180-181` (`source_read`, `_SOURCE_READER_READY=False` — мёртвый флаг), карта `direct_chat_service.py:2369-2375` намеренно без `source_read`, билдеры `capability_registry.py:794-871` |
| UI | **ARCHITECT_NOT_NEEDED** | capability-состояния уже рендерятся общей панелью; новых экранов не требуется |
| Write scope слайса | **ARCHITECT_ADJUSTMENT_REQUIRED** | `slice-graph.json:876-885` не содержит `tool_schemas.py`, `config/settings.py`, `tool_loop.py`, `capability_registry.py` |

## 1. Контракт инструмента

Имя: **`read_source_code`** (проектный naming: snake_case, глагол+объект, как `fetch_article`).
Один инструмент, три операции внутри — по требованию §1.2 («не обязательно отдельные LLM-tools»).

Схема (`services/tool_schemas.py`, рядом с `TOOL_FETCH_ARTICLE`, стиль `:538-598`: `additionalProperties: False`):

```
operation: enum["discover","locate","read"]            (required)
url:       string   — github.com/... /blob/… /tree/… , raw.githubusercontent.com, api.github.com
repo:      string   — "owner/name" (когда ссылки нет)
query:     string   — что искать: имя класса/метода/механизма естественным языком
ref:       string   — ветка/тег/commit как ОТДЕЛЬНОЕ поле (слэши допустимы)
path:      string   — путь файла внутри репозитория
symbol:    string   — идентификатор: класс/метод/поле
line_start/line_end: integer ≥1 (опционально; окно чтения)
follow:    boolean  — разрешить ограниченный обход смежных файлов (default true для "read")
language:  string   — подсказка языка, ТОЛЬКО как сигнал ранжирования (не фильтр-словарь)
```

`required: ["operation"]`, `additionalProperties: False`. Любой аргумент, кроме `operation`, может быть выведен из `ToolContext` (`resolved_url` — существующий резолв ссылки, `tool_router.py:1246-1249`; `query` — `ctx.query`). Нет ни URL, ни repo, ни query → `status:"error"`, `error.code:"invalid_url"`.

### 1.1. Результат (JSON, один объект; НИКОГДА не бросает)

```
status        ok | ambiguous | not_found | unsupported | error        (закрытый набор)
stage         discover | locator | fetch | followup                  (§1.2.5: стадии различимы)
verified      bool                                                   — см. инвариант V1
host          "github.com"
repo          "owner/name"
ref           запрошенная ветка/тег (как пришла)
commit        40-hex commit, к которому привязано чтение           ← провенанс
path          путь файла внутри репозитория
source_kind   file | directory | repo | readme | issue | pull | release | other
verified_url  https://github.com/<o>/<r>/blob/<commit>/<path>#L<a>-L<b>   (commit-pinned)
line_range    [a, b]        номера строк доставленного фрагмента (1-based, включительно)
snippet       сам код с номерами строк (единственная копия текста в payload)
snippet_chars, file_total_lines, language
symbol, symbol_found (bool), parameter_only (bool)
truncation    {truncated, why, effective_limit, limit_source, retrievable_remainder_lines}
not_checked   {files_considered, files_read, depth_left, reason}   — «что НЕ проверено»
followup_incomplete (bool)
candidates    [{repo, stars, language, description, url}]  — только для discover/ambiguous
error         {code, stage, http, retryable, detail}               — только для error
provenance    {provider, endpoint, fetched_at, bytes, sha256, read_level, network_calls}
read_level    reused | discovered | snippet | fetched | parsed | selected (словарь source_reuse:48-56)
reused, network_calls, latency_ms
```

Совместимость с конвейером: `status:"not_found"/"unsupported"` → ToolResult `empty`; `error` → `error`; `ambiguous` → `ok` (исследование удалось, нужен выбор). Правок в `tool_result.classify_output` не требуется. `provenance.sha256` — от полученных байт (не от HTML-страницы), `provenance.endpoint` — id вызова провайдера (`contents|blobs|raw|tree|commits|search.repositories`), без URL с токенами.

### 1.2. Инвариант V1 — что доказывает `verified=true`

`verified=true` выдаётся только если ОДНОВРЕМЕННО:
1. HTTP 200 от source-endpoint провайдера для точной идентичности `(repo, commit, path)`;
2. получены непустые байты файла (декодирование без ошибок для объявленной кодировки);
3. `line_range` вычислен из этих байт, а `snippet` — их точная подстрока (проверяется в коде);
4. `verified_url` содержит commit, а не изменяемую ветку;
5. `source_kind == "file"`.

Никогда не `verified`: поисковые сниппеты, README/issues/releases/wiki, листинг дерева (только пути), очищенный HTML blob-страницы, «вероятный класс», ответ модели. Это прямая реализация §1.4.4 (`search_found ≠ source_fetched`). `verified=false` + `read_level` в `{discovered, snippet}` — единственно допустимая форма «нашёл, но не прочитал».

## 2. Граница провайдера

Новый модуль `services/source_reader.py` (объявлен в write_scope). Внутри:

```python
class SourceProvider(Protocol):            # 6 методов, все async
    name: str
    async def search_repos(query, *, limit) -> list[Repo]
    async def resolve_repo(owner, repo) -> Repo | None
    async def resolve_commit(repo, ref) -> str | None
    async def list_tree(repo, commit) -> TreeListing          # .entries, .truncated
    async def read_file(repo, commit, path) -> SourceFile     # .data(bytes), .sha, .size

class SourceReader:                        # оркестратор: discovery→locator→fetch→followup
    def __init__(self, *, fetcher: SafeFetcher | None = None,
                 provider: SourceProvider | None = None,
                 search=None, settings=None)
```

**Единственная реализация сейчас — GitHub.** Остальные хосты (gitlab, bitbucket, gitea, raw-зеркала) → `status:"unsupported"`, `error.code="provider_unconfigured"`, `detail:"host_not_supported"`. Никаких заявлений о поддержке: `SUPPORTED_HOSTS = {"github.com"}` и проверка по hostname нормализованного URL, а не по строке (защита от `github.com.evil.tld`).

Транспорт — строго существующий `services.safe_fetch.py` (его docstring: «единственный; второй запрещён», `:505`):
* `SafeFetcher.fetch_json(...)` — JSON-эндпоинты; `SafeFetcher.fetch(...)` — байты файла;
* SSRF/редиректы/таймауты/размеры — `guarded_target/aguarded_target`, `_request` с peer-проверкой, `Profile("html", max_bytes=…)`;
* ошибки — `SafeFetchError.code/stage/retryable` переносятся в `error.*` и в out-of-band сигнал `_tool_result.set_signal` (как `tool_router.py:2734-2741`), не в свободный текст;
* авторизация (опционально): заголовок `Authorization`, значение только из env `SOURCE_READER_GITHUB_TOKEN`; в логи/события/`error.detail` не попадает НИКОГДА (`safe_fetch.mask_url/mask_text` для любых строк, где может быть URL).

Эндпоинты и slash-безопасность ref (важно для веток вида `feature/foo`):

| Шаг | Вызов | Почему безопасно |
|---|---|---|
| discovery | `GET /search/repositories?q=…` | не требует токена; лимит 10/мин |
| repo | `GET /repos/{o}/{r}` → `default_branch`, `language`, `stargazers_count` | обязательный id |
| ref→commit | `GET /repos/{o}/{r}/commits?sha={ref}&per_page=1` | `ref` в **query** → слэши однозначны |
| дерево | `GET /repos/{o}/{r}/git/trees/{commit}?recursive=1` | path-параметр = 40-hex, слэшей нет; `truncated` |
| файл | `GET /repos/{o}/{r}/git/blobs/{blob_sha}` (base64+size) **или** `raw.githubusercontent.com/{o}/{r}/{commit}/{path}` | слэши безопасны: blob_sha/commit — hex; raw — готовый путь |
| содержимое по ref | `GET /repos/{o}/{r}/contents/{path}?ref={ref}` | `ref` в query; 404 = нет такого ref/пути |

`/search/code` **не использовать**: официально требует аутентификации (10/мин при токене, только default-ветка, файлы <384 KB). Поэтому локатор строится на дереве, а не на code search — это и есть «без новых жёстких словарей».

Blob-URL → (ref, path): сегменты после `<owner>/<repo>` разбираются перебором кандидатов «самый длинный ref первым», максимум 4 проверки `contents?ref=`; первый 200 = истина, остальные не выполняются. Ссылки на commit (`/blob/<40hex>/…` или `/blob/<7+hex>/…`) распознаются как commit, а не как ветка.

## 3. Discovery и локатор без новых словарей

Discovery (три входа — три равноправных сценария §1.1):
1. **Ссылка дана** → 0 поисковых вызовов: разбор URL (`smartmodule_urls.extract_urls :36-42`, уже используется `fetch_article` :2636-2637), `hostname` → провайдер.
2. **Только имя/примерное имя репозитория** → `GET /search/repositories?q=<query>` (сортировка по релевантности GitHub) + параллельно существующий каскад `deps.search.search(query, cap)` (`search_aggregator.py:510-620`) для опечаток и «человеческих» названий; из текста выдачи вынимаются github-URL регулярным выражением по URL-форме (не по именам проектов) → `(owner, repo)`.
3. **Только описание механизма** → только каскад (он умеет естественный язык), затем проверка кандидатов `GET /repos/{o}/{r}` (≤3).

Ранжирование (сумма баллов, без словарей имён): явная ссылка (+100) > попадание пути `/blob/` в выдаче (+40) > перекрытие токенов запроса и `full_name`/`description` (переиспользуется `search_aggregator.term_key/_term_keys :139-172`, +0..25) > совпадение названного языка (+10) > `log10(stars)` (+0..15) > свежесть `pushed_at` (+0..5). Все сигналы — из ответов API, ни один не выдуман.

Неоднозначность: если два верхних кандидата — разные `owner/repo` и разрыв < 25% балла → `status:"ambiguous"`, `candidates` (≤3, с звёздами/языком/описанием), `needs_choice:true`, и одна сформулированная развилка в поле `question`. Модель задаёт РОВНО один вопрос (§1.3) и никогда не подменяет выбор сама. Один кандидат с отрывом → чтение без вопросов.

Различение кода и документации — по форме URL и по фактическому endpoint, а не по названию: `file` (blob/contents/blobs/raw), `directory` (`/tree/`), `repo`, `readme`, `issue` (`/issues/`), `pull` (`/pull/`), `release` (`/releases/`), `other`. Только `file` может стать `verified`.

Локатор: дерево (1 запрос, `truncated` учитывается) → отбор путей по (a) стему файла = искомый идентификатор, (b) сегментам пакета из запроса, (c) расширениям, соответствующим языку репозитория; понижение приоритета `test/`, `docs/`, `example/`, `README*`; отбор ≤3 путей. Каждый кандидат подтверждается чтением байт и проверкой вхождения `symbol` — «нашли по имени файла» без байт не считается чтением. `list_tree().truncated=true` (лимит дерева: 100 000 записей / 7 MB) → `not_checked.reason="tree_truncated"` и обход через `GET /contents/<dir>` для конкретной подпапки.

## 4. Bounded follow-up

Конфигурируемо (env-only ClassVar, прецедент `ARTICLE_TOOL_ENABLED`):
`SOURCE_READ_MAX_FILES` (default 3, потолок 6), `SOURCE_READ_MAX_DEPTH` (default 1, потолок 2),
`SOURCE_READ_MAX_REQUESTS` (default 8, потолок 16 — жёсткий предохранитель против ретрай-петли),
`SOURCE_READ_MAX_FILE_BYTES` (default 2_000_000 — через `SafeFetcher.fetch(max_bytes=…)`),
`SOURCE_READ_ENABLED` (kill-switch), `SOURCE_READ_GITHUB_TOKEN` (пусто = анонимно).

Порядок: из проверенных байт извлекаются идентификаторы, реально использованные в теле найденного символа (регэксп по формам вызова/наследования/типов — синтаксис, не словарь имён), пересекаются со стемами дерева → дочерние файлы ранжируются и читаются в пределах бюджета. Каждый прочитанный файл — отдельный элемент `files[]` с собственными `verified/line_range/verified_url`, чтобы Writer видел цепочку, а не один файл.

Случай §1.2.4 «первый файл лишь выставляет параметр»: если `symbol` встречается только в объявлении поля/присваивании/конструкторе (`parameter_only=true`, детерминированная проверка форм строки), инструмент обязан выполнить follow-up (если `follow=true` и бюджет позволяет) и вернуть цепочку; если бюджет исчерпан — `followup_incomplete=true` + `not_checked.reason="budget"` и явный список непроверенных кандидатов. Модель не имеет права утверждать поведение по одному параметру (§1.2.4).

Честность «что не проверено» — обязательное поле `not_checked`: количество рассмотренных/прочитанных файлов, остаток глубины и причина остановки (`budget`, `depth_limit`, `tree_truncated`, `not_found`, `rate_limit`).

## 5. Таксономия отказов (0 новых кодов `REASON_CODES`)

| Факт | payload `error.code` | `mca_events.reason_code` |
|---|---|---|
| 404: нет repo/ref/path/файла | `source_missing` | `source_missing` |
| 403/429 при `x-ratelimit-remaining: 0`, `retry-after` или 429 | `rate_limit` | `rate_limit` |
| 403 без rate-limit-заголовков (приватный/закрытый) | `auth_failed` | `auth_failed` |
| 5xx, отказ соединения | `provider_unavailable` | `provider_unavailable` |
| наш дедлайн | `safe_fetch_timeout` | `safe_fetch_timeout` |
| SSRF/scheme/credentials/redirect/размер | код `SafeFetchError` как есть | тот же код |
| HTML вместо кода / битый JSON | `parse_error` | `parse_error` |
| поиск ничего не дал | `no_relevant_results` | `no_relevant_results` |
| хост не поддержан | `provider_unconfigured` | `provider_unconfigured` |
| kill-switch OFF | `disabled` | `disabled` |
| два реально разных кандидата | (не error) `ambiguous` | `ambiguous_identity` |

Прецедент переиспользования вместо расширения словаря — `mca_events.py:263-268` («прочие причины … переиспользуются»). Никаких новых кодов, правок `REASON_CODES` и пин-тестов (314) не требуется.

Формулировки для пользователя (Writer обязан опираться на код, а не догадку): `rate_limit` — «хостинг ограничил частоту запросов (HTTP 403/429, остаток 0), повтор после сброса окна»; `auth_failed` — «хостинг отказал в доступе (HTTP 403)»; `source_missing` — «файла/ветки по этому пути нет (HTTP 404)»; `safe_fetch_timeout` — «чтение не уложилось в таймаут». Запрещено: «GitHub меня не пустил» при пустой выдаче поиска, «код недоступен» при неподдержанном хосте без указания `provider_unconfigured`.

## 6. Конфиг, телеметрия, приёмка

Kill-switch и бюджеты — env-only `ClassVar` в `config/settings.py` (`_env_bool/_env_int_min`, рядом с `ARTICLE_TOOL_ENABLED :1431-1436`); гейт анонса в `tool_schemas.read_source_code_enabled()` по образцу `_article_tool_enabled :896-902` (OFF → инструмент не объявлен, старые вызовы получают честный `disabled` от диспетчера). Никаких новых записей в `param_catalog`/PG, миграций и UI-тумблеров: сетевой модуль, не owner-настройка.

Анонс: `TOOL_READ_SOURCE_CODE` в `TOOL_CALLING_TOOLS` → канон 15→16 (механическое обновление пин-тестов `len(TOOL_CALLING_TOOLS)==15` и списков `names`). Плюс `METERED_TOOLS` (`tool_loop.py:61-65`) — инструмент делает сетевую работу; существующий cap 4 метрированных вызовов сам ограничивает серию исследований. Промпт-канон НЕ правится: `chat_prompts` перечисляет только 3 инструмента при 15 анонсированных (прецедент `chat_prompts.py:98-102`), схема сама себя описывает.

Телеметрия (R17: без текста кода, без URL, без токенов): один стадийный эмиттер `mca_retrieval_context.emit_stage_event("source_"+stage, outcome, reason_code=…)` → durable `mca-13` событие `mca07_source_read` с полями `stage, repo_present, ref_kind(branch|tag|commit), path_depth, language, files_read, network_calls, http_status_class, reason_code, verified, line_count`. Стадии `discovery/locator/fetch/followup` различимы по `stage` (§1.5 — «если исторических трасс нет, добавляем телеметрию на будущее»).

Карта тестов (`tests/test_evol_source_reader.py`, провайдер мокается ТОЛЬКО на транспорте: `SafeFetcher(client=AsyncClient(transport=httpx.MockTransport(handler)))` — прецедент `tests/test_mca02_safe_fetch_round1027.py:29`) — 1:1 к §1.5:

| # | Сценарий §1.5 | Проверка |
|---|---|---|
| 1 | прямая blob-ссылка | `/blob/<ref>/<path>#L…` → `verified=true`, верный `commit`, точный `line_range`, `snippet` — подстрока байт |
| 2 | имя репозитория + описание механизма | discover→locate→read по фикстуре дерева; связанный файл, `verified=true` |
| 3 | только описание, без имени | либо найден репозиторий, либо `status:"ambiguous"` + ≤3 кандидата + ровно один вопрос, без выдуманного выбора |
| 4 | класс только выставляет параметр | `parameter_only=true` → цепочка ≤`MAX_FILES`, `not_checked` заполнен, нет утверждения поведения по параметру |
| 5 | 403/404/rate limit/timeout/HTML/сниппет | по одному кейсу на строку таблицы §5: `verified=false`, честный код, нет псевдо-URL |
| 6 | прошлые реплики/даты | инструмент не синтезирует цитаты/даты: в payload нет полей времени сообщений; поправка пользователя не создаёт новую хронологию (проверяется на уровне payload+Writer-инструкции, без LLM) |
| 7 | без лишних вызовов/утечек/исполнения | повторный `read` того же `(repo,commit,path)` = `reused=true`, `network_calls=0` (`source_reuse`); ни один лог/событие/payload не содержит токена; скачанный код не исполняется (нет `exec/eval/importlib/subprocess` в модуле — тест-инвариант) |

Живых внешних вызовов для приёмки не требуется (`live_required:false`, `live_when:preprod` в `requirements-map.json:13017`). Живой прогон — один, на preprod, как подтверждение, не как гейт.

## 7. Параллельная безопасность

Одна Builder-полоса. Файлы (правки — аддитивные, «новое в хвост»):
`services/source_reader.py` (новый), `services/tool_router.py` (метод `_read_source_code` + запись в `dispatch`-registry `:1335-1353`), `services/tool_schemas.py` (схема + канон), `config/settings.py` (env-переменные), `services/tool_loop.py` (`METERED_TOOLS`), `services/capability_registry.py` (`source_read` через `_build_from_announced :757-785`), `services/direct_chat_service.py` (строка в `_EVIDENCE_CAP_REGISTRY :2369-2375`), `services/evidence_policy.py` (`_SOURCE_READER_READY=True` — снять мёртвый флаг/оставить комментарий), `tests/test_evol_source_reader.py`, `plans/features/evol/audit/w6-source-reader.md`.

**Не трогать:** `services/prompt_registry.py`, `services/chat_prompts.py`, `services/prompt_migrations.py` (канон без ревизии), `services/web_content_extractor.py` (использовать как есть; trafilatura-каскад для кода НЕ применять), `services/search_aggregator.py`, `services/safe_fetch.py` (только импорт), Summary/Memory/Dream (`summary_*`, `mca_dream_*`), cover/style (`cover_style_*`, `style_policy.py`), `handlers/**` (проводка ToolDeps — `bot.py:599-615`; если DI всё же нужен, это единственная строка в `bot.py`), `services/agentic_events.py`, `services/mca_events.py` (0 новых кодов).

Классификация: `tool_schemas.py`, `config/settings.py`, `tool_loop.py`, `capability_registry.py` — **SERIALIZE** (общие для всех tool-волн и счётчиков), остальные **PARALLEL_SAFE** внутри одной полосы. Обновление пин-тестов `len(TOOL_CALLING_TOOLS)==15` — часть той же полосы, до передачи Reviewer (иначе красный набор).

## 8. Риски и UNKNOWNS

* **R2 — квота GitHub без токена:** 60 запросов/час на IP (документировано), дерево+commits+blobs ≈ 5–7 запросов на одно исследование → несколько исследований в час и честный `rate_limit` после. `raw.githubusercontent.com` отдаёт байты без REST-квоты (не REST-эндпоинт) — снижает расход, но это нужно подтвердить в живом прогоне.
* **R2 — `raw.githubusercontent.com` для приватных/удалённых файлов** возвращает 404 без деталей; fallback порядок: `blobs` (sha) → `contents?ref` → `raw`; каждый шаг — отдельная запись `provenance.endpoint`.
* **R1 — ветки со слэшами:** решено query-параметрами (`commits?sha=`, `contents?ref=`); перебор ≤4 кандидатов при разборе `/blob/`-URL. Неподтверждённый остаток: ref, содержащий и `/`, и совпадающий с началом пути (редкий, покрыт перебором).
* **R2 — дерево >100 000 записей/7 MB** (`truncated=true`) → `not_checked.reason="tree_truncated"`, деградация на `/contents/<dir>`.
* **R3 — HTML-fallback отсутствует намеренно:** очищенная blob-страница не даёт commit-pinned line-accurate провенанс; вместо псевдо-`verified` возвращается честный отказ. Если позже понадобится — только как `verified=false, read_level="parsed"`.
* **R2 — язык/символ не найден:** `status:"not_found"` + `not_checked`, без «вероятного класса»; риск ложного «не существует» снимается тем, что 404 отделён от «в дереве нет совпадений».
* **R1 — границы репозитория (submodule/symlink):** `contents` может вернуть `symlink`/`submodule`; читаются как `unsupported` с честным `detail`, без рекурсии наружу.
* **UNKNOWN:** фактическое поведение GitHub при 403 «secondary rate limit» без `retry-after` — код `rate_limit` и без ретраев (ретраи запрещены условием §1.2).

## 9. Порядок работ (одна полоса)

1. `source_reader.py` + скелет тестов на транспортных фикстурах (V1-инвариант в тесте первым).
2. Схема + канон + kill-switch + `METERED_TOOLS` + пин-тесты.
3. `_read_source_code` в роутере: `_evidence_window("code")` → `_record_limit` → `source_reuse.store` (claim_keys из `_claim_keys :1424-1450`) → JSON-payload.
4. Проводка capability/evidence (2 строки в `capability_registry`, 1 строка в `_EVIDENCE_CAP_REGISTRY`).
5. Телеметрия стадий; затем отчёт `plans/features/evol/audit/w6-source-reader.md` с фактическими кодами отказов.

---

**Итог (RU).** Переиспользуем существующие контуры: `SafeFetcher` (SSRF/редиректы/лимиты/маскирование), окно evidence, `source_reuse`, ToolResult и словарь причин — новых кодов и новых пайплайнов нет; новое только сам `read_source_code` и GitHub-адаптер.
Контракт заморожен: один инструмент с операциями discover/locate/read, `verified=true` только по реальным байтам файла с commit-pinned ссылкой и точным диапазоном строк; неоднозначность — один вопрос, отказы — существующие коды без выдуманных причин.
Нужно одно решение владельца/PM: расширить write_scope слайса на `tool_schemas.py`, `config/settings.py`, `tool_loop.py`, `capability_registry.py`, `evidence_policy.py` (механические аддитивные правки), иначе Builder не сможет объявить инструмент легально.
