# F0.2 — Аудит механизмов сохранения (`f0-config-bugfixes-round1025`)

> Раунд 10.25, T-2420…T-2426. Канон write-path: `persistItems()` (client) →
> `POST /api/config` (chat/global) → атомарная серверная запись
> (`set_chat_params` для chat; атомарный `ConfigCache.set_many` для global).
> Секреты — отдельный BYOK-путь `/api/config/keys/own` (§50, F9). R17: секретов
> в артефактах нет.

## 1. Инвентарь «экран → ключ(и) → read API → write API → scope» (T-2420)

| # | Экран / механизм | Ключ(и) | read API | write API | scope |
|---|---|---|---|---|---|
| 1 | Тумблеры модулей | `flags.*` | `GET /api/config` | `POST /api/config` | chat / global |
| 2 | Системные промпты | `prompts.direct_chat_system_prompt`, `prompts.synthesizer_*` | `GET /api/config` | `POST /api/config` | chat / global |
| 3 | Промпты Синтезаторов | `prompts.*` (stage=synthesizer) | `GET /api/config` | `POST /api/config` | chat / global |
| 4 | Промпты Вербализаторов | `prompts.*` (stage=verbalizer) + `prompts.verbilizer_default_mode` | `GET /api/config` | `POST /api/config` | chat / global |
| 5 | Модели | `models.*` | `GET /api/config` | `POST /api/config` (`global:true`) | global |
| 6 | Провайдеры (base_url/display) | `models.*` | `GET /api/config` | `POST /api/config` (`global:true`) | global |
| 7 | Резервные подключения | `models.*`, `keys.*` | `GET /api/config` | `POST /api/config` / BYOK | global |
| 8 | API-ключи | `keys.*` | `GET /api/config` (`{configured,last4}`) | `PUT /api/config/keys/own` (и image-вариант) | global (BYOK) |
| 9 | Числовые лимиты | `limits.*` | `GET /api/config` | `POST /api/config` | chat / global |
| 10 | Память | `memory.*`, `limits.*` (memory) | `GET /api/config` | `POST /api/config` | chat / global |
| 11 | Анти-клише | `limits.anticliche_max_patterns` | `GET /api/anticliche` | `POST /api/config` (`global:true`) / `PUT /api/anticliche` | global-only |
| 12 | PERMsoc (матрица) | `perm_overrides` | `GET /api/config`, `/api/access` | `POST /api/config`, `/api/access` | chat |
| 13 | Глобальные настройки | `content.*` (info/guide), прочие | `GET /api/config` | `POST /api/config` / спец-эндпоинты info/guide | global |
| 14 | Локальные переопределения | `chat_params.overrides` | `GET /api/config` (X-Chat-Id) | `POST /api/config` (X-Chat-Id) + reset-эндпоинт | chat |

«Сирот» нет: каждый механизм читается через `GET /api/config` (или профильный
GET для анти-клише) и пишется через единый канон (`POST /api/config`) либо
явно выделенный BYOK-путь секретов.

## 2. Цикл `load → edit → save → re-read → compare` (T-2421)

HTTP 200 сам по себе не доказательство — во всех прогонах сравнение идёт с
повторным чтением. **Честная градация доказательств** (без «живого» прод-стенда
в этой итерации): `unit` = автотест с повторным чтением на уровне API/сервиса;
`live` = приёмка в Telegram/TMA (вне зоны @Builder).

| Механизм | load | save 200 | re-read | compare | Доказательство |
|---|---|---|---|---|---|
| chat-override (Fallback/лимиты/флаги) | ✓ | ✓ | `set_chat_params` → root | совпадает | `unit`: `test_normal_write_emits_notify_and_history`, `test_scope_isolation_chat_a_not_b` |
| глобальный (модели/промпты) | ✓ | ✓ | `GET /api/config` | совпадает | `unit`: `test_summary_aliases_widget_keyvalue_and_json_roundtrip`, `test_settings_persistence_round1014` |
| глобальный per-key optimistic | ✓ | ✓/revalidated/409 | `cache.get_updated_at` | совпадает/конфликт | `unit`: `test_global_config_optimistic_round1025.py` (4 теста) |
| секреты (`keys.*`) | ✓ (`{configured,last4}`) | ✓ (BYOK) | `GET /api/config` | `configured=true`, значение не выводится | `unit`: `test_webapp_api.py` |
| анти-клише | ✓ | ✓ | `GET /api/anticliche` | `count`/`final_count` | `unit`: `test_anticliche_semantics_round1025.py` |

`live`-подтверждение (скриншоты TMA, мобильный браузер) — T-2419/T-2433/T-2454;
в этом отчёте **не заявляется** (нет прод-доступа).

## 3. Спец-кейсы §2.3 (T-2422)

| Кейс | Покрытие |
|---|---|
| Несколько полей одной формы | `persistItems` — один POST на scope-пакет; `saveModalEdits` |
| Двойной тап | guard in-flight по ключу (`this.saving`), `saveConfigItem`/`persistItems` |
| Переключение чата во время запроса | `scopeEpoch`/`_scopeGuard` — устаревший ответ игнорируется |
| Две сессии | server `D-409-2` (advisory-lock) + `D-409-1` short-circuit |
| Сохранение рядом с API-ключом | секреты не смешиваются с общим POST (BYOK) |
| Частичные ошибки | `OperationResult.failed[]` + один warn-тост |
| Устаревшие ответы | `scopeEpoch` + `_scopeGuard` |

## 4. Scope-изоляция (T-2423)

- тест `test_scope_isolation_chat_a_not_b`: запись в чат A не меняет чат B;
- `global → local → global` не теряет значения (namespace-мерж в
  `set_chat_params`, `_root_with_meta` сохраняет все namespace);
- «копии конфигурации под визуальный экземпляр» не создаётся — write идёт по
  ключу, не по DOM-узлу.

## 5. Канонический write-path (T-2424)

| Источник | Статус |
|---|---|
| `persistItems()` (единая точка клиента) | **канон** (F0) |
| `saveConfigItem`/`saveBlock`/`saveModalEdits`/`savePromptFallbackMode`/`selectPromptMode` | делегируют в `persistItems` |
| `POST /api/config` chat | `set_chat_params` (+ `D-409-1/2`) |
| `POST /api/config` global | атомарный `ConfigCache.set_many` (`D-409-3`) + per-key optimistic (`revalidated`/409 `conflicting`) |
| `PUT /api/config/keys/own` | BYOK-путь секретов (не дублируется) |
| `PUT /api/anticliche` | анти-клише (отдельная сущность) |

Тест паритета источников: после записи любым механизмом `GET` отдаёт то же
значение (см. §2).

## 6. Регресс-тесты (T-2425)

- `tests/test_save_state_machine_round1025.py` — chat-запись, short-circuit,
  конфликт, scope-изоляция (секреты наружу только `{configured,last4}`);
- `tests/test_settings_persistence_round1014.py` — промпты/модели/глобальный
  write-path, health-инвалидация;
- `tests/test_webapp_api.py` — round-trip промптов/алиасов (без значений
  секретов).

Δ каталога = 0 (REGISTRY 459 / GROUPS 98 / `_TAB_BY_GROUP` 96 — тест-инвариант
зелёный). Δ DDL = 0.
