# REVIEW — EMBED-FALLBACK-FIX (F2 аудита 23.10)

Лейн: **REV-EMBED-FALLBACK**. Режим: read-only; единственная запись — этот файл.
Дата: 2026-10-23 (локально UTC+12).

Кандидат: **`468d1041904d024d7cffb07b92fb3d417765294d`**.
Родитель: `29161a60` (только docs asap2). Кодовая база для RED `4bd2f3c6` эквивалентна: docs-коммит не трогает код/тесты.

**Вердикт: Approved. В поезд 2.58.112: МОЖНО** (с эксплуатационными условиями из §6; блокирующих дефектов нет).

## 1. Скоуп и привязка

`git show --name-status 468d1041` — ровно 10 файлов: `services/embedding_control_plane.py`, `tests/test_embed_fallback_slots_routing.py`, 8 evidence-файлов. `services/llm_client.py`, `services/param_catalog.py`, `config/settings.py`, миграции, зависимости — не менялись. Новых env-имён, DDL и секретов в диффе нет (скан добавленных строк по `AIza|sk-|password|secret|os.environ|CREATE TABLE|ALTER TABLE` — 0 попаданий).

Проверки выполнены на чистых worktree, а не на грязном master:
- `C:\Users\main\AppData\Local\Temp\opencode\rev-embed-468d1041` = `468d1041`;
- `C:\Users\main\AppData\Local\Temp\opencode\rev-embed-base` = `4bd2f3c6` + копия нового теста (скопирован только тест; код базы не менялся).

## 2. Acceptance ledger (пункты лейна)

| # | Пункт | Статус | Доказательство |
|---|---|---|---|
| 1 | Маршрутизация primary/fallback_1/fallback_2/extra_N; пустой per-slot → общий/primary без исключений | **VERIFIED** | `services/embedding_control_plane.py:344-355` (per-slot connection), `:377-385` (credential), `tests/test_embed_fallback_slots_routing.py:128-208`. Прод-конфиг-симуляция: primary→apinet, fallback_1/2→generativelanguage; extra_N→primary. |
| 2 | Provider/adapter по фактическому host слота; Google-ключ не уходит на apinet и наоборот | **VERIFIED** | `select_adapter`/`_is_gemini_endpoint` `:318-320, :1183-1186`; dispatch `:1366-1369`; adapter передаёт `credential.base_url/model` `:1144-1153`. Тесты `:210-247`; прод-симуляция: primary=openai-compatible, fallback_1/2=gemini. |
| 3 | Identity/квоты: fingerprint учитывает адрес слота; группы/ротация/cooldown не изменены | **VERIFIED** (с оговоркой §5) | Дифф не трогает `profile_identity` `:2246-2261`, `resolve_quota_group_full` `:284-298`, `QuotaGroupRegistry` `:683-724`. Тесты групп/ротации: 112 passed. |
| 4 | Обратная совместимость: extra_N, legacy-каскад при `EMBED_CONTROL_PLANE_ENABLED=false`, тесты без hot-кэша | **VERIFIED** | extra_N — тест `:197-208`; legacy-путь не изменён (`llm_client.py:1615-1669`, профили `:363-407`, `embed_once` `:1684-1739`); прогон нового теста в worktree без `.env`: 8 passed; отдельный пробник с `hot._cache is None` не бросает исключений и даёт прежние settings-дефолты. |
| 5 | Скоуп диффа: только заявленные файлы; нет env/DDL/зависимостей; секретов 0 | **VERIFIED** | См. §1. |
| 6 | Независимый RED/GREEN и смежные наборы | **VERIFIED** | Числа в §3; RED воспроизведён на `4bd2f3c6` (5 failed/3 passed), GREEN на `468d1041` (8 passed). |
| 7 | Инцидентальные находки: классификация и влияние на прод | **VERIFIED** (обе related-nonblocking) | I1 и I2 подтверждены кодом и отдельным экспериментом; см. §4. |

## 3. Независимые прогоны (Windows `.venv`, чистый worktree 468d1041)

| Набор | Результат | Время |
|---|---|---|
| Новый файл `tests/test_embed_fallback_slots_routing.py` | **8 passed** | 10.87 s |
| RED: тот же файл на `4bd2f3c6` (копия теста) | **5 failed, 3 passed** | 11.02 s |
| control plane + asap8-F8 + SOUL-13.4 + asap44 breaker + asap5 identity | **112 passed** | 18.91 s |
| asap6 generations + `test_llm_client` + `test_status_service` + `test_summary_memory` | **251 passed, 1 warning** | 19.59 s |
| `pytest tests -k embed` | **240 passed, 15028 deselected, 1 warning** | 59.37 s |
| graphrag recovery/memory/rebuild + summary wave C/D | **295 passed** | 16.19 s |
| `test_param_catalog` + summary annotation | **39 passed** | 3.93 s |

Числа совпадают с отчётом Builder. Один параллельный прогон graphrag поймал pytest-timeout из-за конкуренции CPU с другим прогоном; чистый последовательный прогон — 295 passed, дефекта нет.

## 4. Инцидентальные находки (проверка классификации)

**I1 — `auth_failed` не сбрасывается при смене ключа. Подтверждено, related-nonblocking.**
`QuotaGroupRegistry._cred_health` живёт только в памяти (`embedding_control_plane.py:683-724`), TTL/reset на изменение hot-ключа нет; снимается успехом того же alias (`:1538-1541`) или рестартом. Отдельный эксперимент: после 401 primary помечен `auth_failed`; после смены ключа в hot-конфиге executor всё ещё берёт fallback; после `reset_runtime()` (эквивалент рестарта) — берёт новый ключ. Прод-деплой штатно делает `systemctl restart admin_bot` (README §Деплой), поэтому старые пометки после релиза снимаются. **Не блокирует**; наоборот, без рестарта фикс мог бы не проявиться на fallback-слотах.

**I2 — legacy-путь резолвит профили в `__init__`. Подтверждено, related-nonblocking.**
`LLMClient.__init__` кэширует `_embed_fallback_profiles` (`llm_client.py:363-407`); при `EMBED_CONTROL_PLANE_ENABLED=false` hot-смена адреса требует рестарта. В проде control plane ON (аудит 23.10: `EMBED_CONTROL_PLANE_ENABLED=True`), горячий путь читает конфиг на каждый вызов; на текущий релиз не влияет.

## 5. Остаточные риски (не блокеры)

1. **Смешение provider'ов в одном индексе.** Identity хранилища (`summary_memory.embedding_identity_fingerprint`, `summary_memory.py:410-451, 1827-1835`) считается по primary-профилю; векторы fallback-слота пишутся под той же identity. Это не изменение данного диффа, но фикс делает fallback реально работающим, поэтому риск становится практическим. В текущем проде у всех трёх слотов `gemini-embedding-001` и dim=3072 (аудит `embed-provider/report.md` §1), поэтому смешения размерности/модели нет; apinet отдаёт ту же модель gemini-embedding-001 (по аудиту). Если владелец позже поставит fallback-слоту другую модель — потребуется reindex, менять модель без него нельзя. Отдельная задача-гвард, не F2.
2. **Live-проверка маршрута после деплоя** — только по логам/панели: `credential_rows[*].provider` должен стать `generativelanguage.googleapis.com` у fallback_1/2, а при реальном failover в логе `LLM request OK | url=...` — Google-host, без `embed credential auth_failed` для этих alias. Пока идёт identity-rebuild (текущий прод: FTS-only до нового fingerprint), судить по числу векторов нельзя.
3. **Устаревшие строки `embedding_quota_state`** (primary/fallback_1/fallback_2 `exhausted` до 2026-10-23T00:05Z) остаются в SQLite, но после явных labels владельца (`primary:apinet_paid,fallback_1:google_free_1,fallback_2:google_free_2`, 17:15Z) активны новые healthy-группы. Фикс квоты не меняет; на live-проверку влияет только через выбор группы.

## 6. Что нужно сделать после деплоя (условия «можно в поезд»)

1. Убедиться, что сервис перезапущен (иначе старые `auth_failed` в памяти сохранятся).
2. В панели `/api/memory/embeddings` / `credential_rows`: у fallback_1/2 `provider = generativelanguage.googleapis.com`, `model = gemini-embedding-001`, группы `google_free_1/2` source=explicit, health=healthy.
3. При первом реальном сбое primary проверить лог: вызов идёт на Google-host, `auth_failed` на fallback-слотах не появляется. Опционально — один cosine-замер primary vs fallback на одинаковом тексте (подтверждение единого пространства; при расхождении не включать fallback-запись до reindex).

## 7. Что не проверялось

- Прод/SSH/сетевые вызовы — запрещены лейном; live-панель и реальный failover остаются за DevOps после деплоя.
- UI/Playwright/Browser Use — изменений UI/CSS/JS нет; меняются только данные `credential_rows`, проверенные unit-тестом и прод-симуляцией.
- Внешняя эквивалентность apinet и Google — `EXTERNAL_UNVERIFIED`; аудит подтвердил только dim=3072 и HTTP 200 на обоих.

## 8. Следующее действие

Оркестратору: включить `468d1041` в поезд 2.58.112 как есть (код-фикс готов), передать DevOps пункты §6. Повторное ревью кода не требуется; при изменении `services/embedding_control_plane.py` или теста — обязательна повторная привязка.