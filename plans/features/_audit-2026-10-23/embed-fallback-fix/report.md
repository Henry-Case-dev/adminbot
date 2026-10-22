# EMBED-FALLBACK-FIX — per-slot endpoint для запасных слотов эмбеддингов

Дата: **2026-10-23** (локально UTC+12). Лейн: `EMBED-FALLBACK-FIX`.
База: `4bd2f3c6`. Прод не трогался, `.env`/конфиг/прод-БД не менялись, деплоя нет.

## 1. Причина (находка F2 аудита 23.10.2026)

`build_credential_pool()` считал **один** `base_url`/`model` (primary) и
подставлял его **всем** credential'ам. Отдельные адреса запасных слотов
(`models.embedding_fallback1_base_url`, `models.embedding_fallback2_base_url`)
читались только резолвером профилей (`resolve_embedding_profiles`) — для
панели/identity, но **не для dispatch'а**. Следствие на проде: два Google-ключа
слались на apinet-endpoint, получали 401 и помечались `auth_failed` — запасные
слоты не выполняли свою роль при сбое primary.

До (HEAD `4bd2f3c6`, `services/embedding_control_plane.py`):

```text
327:    base_url = str(_hot_get("models.embedding_base_url", ...))
330:    model    = str(_hot_get("models.embedding_model_name", ...))
333:    provider = _provider_of(base_url)
...
356:        pool.append(EmbeddingCredential(
357:            alias=alias, api_key=key, base_url=base_url, model=model,
358:            provider=provider, quota_group_id=group,
```

После (working tree):

```text
344:    profiles = resolve_embedding_profiles()          # hot → env → легаси-общий
349:    def _connection(alias) -> tuple[str, str]:       # свой → общий → primary
...
379:        slot_base, slot_model = _connection(alias)
380/382:    base_url=slot_base, model=slot_model, provider=_provider_of(slot_base)
```

## 2. Как теперь маршрутизируются слоты

| alias | base_url | model | provider |
|---|---|---|---|
| `primary` | `models.embedding_base_url` → `EMBEDDING_BASE_URL` | `models.embedding_model_name` → `EMBEDDING_MODEL_NAME` | host своего адреса |
| `fallback_1` | `models.embedding_fallback1_base_url` → легаси-общий `models.embedding_fallback_base_url`/`EMBEDDING_FALLBACK_BASE_URL` → primary-адрес | `models.embedding_fallback1_model` → легаси-общий `…fallback_model` → primary-модель | host своего адреса |
| `fallback_2` | `models.embedding_fallback2_base_url` → адрес Fallback 1 → primary-адрес | `models.embedding_fallback2_model` → модель Fallback 1 → primary-модель | host своего адреса |
| `extra_N` | primary-адрес (своего каталога нет — как раньше) | primary-модель | host primary |

Источник истины — **существующий** резолвер `resolve_embedding_profiles()`
(он же питает панель, статус и identity-отпечаток), поэтому dispatch, панель и
identity больше не могут разойтись по адресу. Пустой per-slot адрес никогда не
бросает исключение: цепочка всегда заканчивается primary-значением (прежнее
поведение).

Квоты/группы и ротация **не изменены**: группы по-прежнему
`keys.embedding_quota_group_labels` → auto-alias (`primary`/`fallback_1`/
`fallback_2`) → `unknown` (только `extra_N`); `429` одной группы не трогает
другие, `401` помечает только свой credential.

Исполнение: `EmbeddingExecutor` передаёт `credential.base_url/model` в
`LLMClient.embed_once(..., base_url=, model=)`; адаптер выбирается по host'у
**слота** (`select_adapter`), поэтому Google-слот идёт через
`GeminiEmbeddingAdapter` (лимит 2048 token/item), apinet — через
`OpenAICompatibleEmbeddingAdapter`. Изменений в `services/llm_client.py` не
потребовалось: legacy-каскад там уже per-profile
(`_embed_fallback_profiles` + `_post_embed_fallback(base_url=, model=)`), а
`embed_once` принимает per-call `base_url/model`. `param_catalog.py` и
`config/settings.py` тоже не менялись — нужные имена/env уже существуют и
описаны корректно.

## 3. RED → GREEN

RED (тесты добавлены до фикса; сервис откатывался `git stash` на HEAD):

```text
5 failed, 3 passed in 3.68s      # red-pre-fix.txt
FAILED test_pool_slots_carry_their_own_base_url_and_model
FAILED test_pool_connection_matches_resolved_profiles
FAILED test_legacy_common_fallback_address_is_used
FAILED test_executor_failover_uses_slot_endpoint        # второй вызов шёл на https://apinet.test/v1
FAILED test_executor_auth_failed_slot_does_not_break_others
```

GREEN: `8 passed` (`green-new.txt`).

Что фиксируют тесты (`tests/test_embed_fallback_slots_routing.py`):

1. три разных base_url/модели → три разных адреса/модели/provider у слотов;
2. dispatch-адрес слота == адрес профиля (панель/identity) — CONTRACT против
   повторного расхождения;
3. незаданный per-slot адрес → общий/легаси → primary (паритет с прежним
   поведением); `extra_N` — соединение primary;
4. сбой primary (429) → следующий слот идёт на **свой** адрес и на свою модель
   (главный RED-кейс), адаптер выбирается по host'у слота;
5. `401` одного слота → `auth_failed` только этого credential'а, остальные
   healthy, следующая логическая попытка идёт на адрес Fallback 1;
6. primary-эмбеддинги независимы от chat-провайдера (регрессии нет).

`TEST-LIFECYCLE: REGRESSION owner=EMBED-FALLBACK-FIX/F2` + `CONTRACT` (см.
docstring теста). Новых provisional-тестов нет.

## 4. Прогоны (Windows `.venv`)

| Набор | Результат | Файл |
|---|---|---|
| новый файл | **8 passed** | `green-new.txt` |
| control plane + asap8-F8 + SOUL-13.4 + asap44 breaker + asap5 identity | **112 passed** | `green-cp.txt` |
| asap6 generations + `test_llm_client` + `test_status_service` + `test_summary_memory` | **251 passed**, 1 warning | `green-adjacent.txt` |
| `pytest tests -k embed` (весь репозиторий, отбор по имени) | **240 passed**, 15028 deselected | `green-k-embed.txt` |
| graphrag recovery/memory/rebuild + summary wave C/D | **295 passed** | `green-graphrag.txt` |
| param catalog (+ summary annotation) | **39 passed** | `green-catalog.txt` |

Команды — `C:\Code\Python\adminbot\.venv\Scripts\python.exe -m pytest <файлы> -q`.
Наборы пересекаются по файлам, поэтому суммы не складываются в «уникальные».

## 5. Риски и что осталось

- **Прод-проверка (нужна после релиза, не выполнена здесь):** при живом сбое
  primary (например, 429/402 apinet) в логах должен появиться вызов Google-слота,
  а `credential_rows[*].provider` — `generativelanguage.googleapis.com` для
  `fallback_1/2`. До релиза на проде поведение не меняется.
- **Историческая маска:** у уже помеченных `auth_failed` ключей состояние живёт
  в памяти до рестарта (`HEALTH_AUTH_FAILED` без TTL). После релиза рестарт
  сервиса нужен, чтобы снять старые ошибочные пометки. Это существующая
  семантика §11, не расширял.
- **Смешение моделей между слотами:** per-slot модель теперь реально
  применяется. Если владелец задаст у fallback-слота другую модель/размерность,
  векторы слота уйдут в тот же индекс — конфигурационный риск (и раньше
  существовал в legacy-каскаде). В проде у всех трёх слотов одна модель
  `gemini-embedding-001` (3072), поэтому риска нет. Гвард-предупреждение о
  расхождении моделей — отдельная задача, здесь не вводил.
- **Откат:** `git revert` одного коммита (изменения локальны для
  `build_credential_pool`), cold-путь без миграций/DDL.

## 6. Инцидентальные находки

| ID | Класс | Факт | Влияние |
|---|---|---|---|
| I1 | related-nonblocking | `auth_failed` не сбрасывается при смене значения ключа в hot-конфиге — только успех того же alias или рестарт (`QuotaGroupRegistry._cred_health`, services/embedding_control_plane.py:695-700) | После исправления ключа слот оживает лишь после рестарта; отдельная задача |
| I2 | related-nonblocking | legacy-путь `LLMClient.embed` резолвит профили фолбэка в `__init__` (кэш на клиенте) — hot-изменение адреса требует рестарта при `EMBED_CONTROL_PLANE_ENABLED=false` | Уже зафиксировано в отчёте аудита §8; штатный путь (ON) читает конфиг на вызов |
