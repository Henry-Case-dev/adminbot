# F8 `parameter-registry-widget-map-round1025` — результаты §117 п.1–4

> **Фича:** F8 (Эпик 1, read-only enabler). **ADR:** `adr-1025-21-parameter-registry-and-config-diff.md` (**Accepted**).
> **Baseline:** HEAD `a40f244`, `APP_VERSION` 2.58.15, каталог **459/98/96/21/418**, pytest **8374/0**, JS **38/38**.
> **Инварианты:** **Δ DDL = 0**, **Δ каталога = 0**, CSP/zero-build, read-only, **R17** (секреты не выводятся), **R18**.
> **Границы:** F8 не переносит UI и не переписывает каталог; аудиты F4–F7/10.14/prod — **источник** (ссылки, не дублирование); §117 п.5–12 — вне F8 (F9/F10/F11).

## 1. §117 п.1–4 — четыре артефакта (REQ-F8-12)

| п. | Требование §117 | Артефакт | Статус |
|---|---|---|---|
| 1 | Карта экранов | `plans/docs/screen-map-round1025.md` (459 строк; `set(param_key) ⊇ REGISTRY`, «без места» = 0) | ✅ |
| 2 | Полный реестр параметров (12 полей §2) | `plans/docs/param-registry-round1025.tsv` (459 строк, 23 колонки) + провенанс `param-registry-round1025.meta.md` | ✅ |
| 3 | Карта виджетов | `plans/docs/widget-map-round1025.md` (Статус/Аналитика/Память/ИИ/Доступы; `api-only` выделен) | ✅ |
| 4 | Подтверждение сохранности конфигурации | `plans/reports/round1025_f8_config_diff.md` (8 срезов; 0 незапланированных изменений) + безопасная точка отката (T-2964) | ✅ |
| — | п.5–12 | **вне F8** (F9 — секреты-UI; F10 — финальный гейт/приёмка; F11 — токены/виджеты) | граница |

## 2. Блок A — обязательный аудит §2 (15 источников, REQ-F8-01)

Read-only аудит; агрегирует существующие аудиты ссылками (не дублирует).

| §2.x | Источник | Артефакт/раздел F8 | Ссылка (источник) |
|---|---|---|---|
| 2.1 маршруты | `web/api/routes.py` (31 маршрут `@api_router`) + `web/api/{access,analytics,anticliche,avatars,chat_lore,gates,memory_agi,oversight}.py`, hash-routing `web/app.js` | `screen-map` (read_api/write_api), раздел 4 | F1 `plans/reports/round1025_f1_*` |
| 2.2 компоненты | `web/app.js` (TABS/HUBS/WORKSPACE_TABS), `web/index.html`, `web/static/*` | `widget-map` (data_source), раздел 5 | F1/F5/F6 отчёты |
| 2.3 формы | `web/index.html` (config-формы, KV/select/textarea), `web/app.js` (saveConfigItem/saveBlock) | реестр `widget`/`validation` | F4/F7 отчёты |
| 2.4 конфигурационные параметры | `services/param_catalog.py` — REGISTRY 459 / GROUPS 98 / `_TAB_BY_GROUP` 96 / TAB_RULES 21 / Settings 418 | реестр (полнота 459/459), `meta.md` (счётчики) | 10.14 `inventory.tsv` (411), `tests/fixtures/round1025/catalog_baseline.json` |
| 2.5 API чтения | `/api/config` GET, `/api/config/params-meta`, `/api/config/keys/own`, `/api/config/keys/status`, `/api/debug/config`, `/api/status`, `/api/memory/*`, `/api/analytics/*` | реестр `read_api`, `widget-map` | F7 отчёт |
| 2.6 API сохранения | `/api/config` POST (global/chat), `PUT/DELETE /api/config/keys/own`, `DELETE /api/config/chat/{key}`, `PUT /api/chat/{cid}/gates`, `PUT /api/access/param_permissions/{key}` | реестр `write_api` | F0 save-audit, F7 отчёт |
| 2.7 модели и провайдеры | `services/param_catalog.py` (models 56, keys 20), `config/settings.py`, `services/llm_client.py` | реестр (category models/keys) | F5 `round1025_f5_ai_map.md` |
| 2.8 промпты | `services/param_catalog.py` `_PROMPTS` (21, `code_source`), `services/summary_prompts.py` (+factcheck/lore/dossier/dream/search/web/youtube) | реестр (`default_value=code:...`) | F5/F6 отчёты |
| 2.9 телеметрия | `services/usage_events.py`, `web/api/analytics.py`, `services/log_ring.py`, `services/uptime_heartbeat.py` | `widget-map` (Аналитика/логи/история ключей) | F6 `round1025_f6_*` |
| 2.10 виджеты Статуса/Сводки | `web/app.js` (Status/Oversight), `web/static/execution_graph.js` | `widget-map` §5 | F6 отчёты |
| 2.11 наследование настроек | `services/chat_params.py` (`overrides`), `services/hot_config.py` (hot.get|get_chat_param), глобал→чат override | реестр `scope`/`inheritance`; `widget-map` | F7 отчёт, `round1025_scope_selector_test.js` |
| 2.12 генеральные переключатели модулей | `services/param_catalog.py` (`flags_module_*`), `web/app.js` (панель быстрого управления) | реестр (flags), `screen-map` → Модули | F4 `module-store` |
| 2.13 локальные функции PERMsoc | `services/param_catalog.py` (`reactions_*`/`flags_permsoc*`/`limits_{alan,kostik,mimic,deadpage,media_permsoc}`), `web/app.js` | реестр (PERMsoc), `screen-map` → PERMsoc | F7 `round1025_f7_*` |
| 2.14 права доступа | `/api/roles*`, `/api/admins*`, `/api/access/param_permissions`, `services/roles.py`, `services/access.py` | реестр `permissions`, раздел 4 | F6 `round1025_f6_*` |
| 2.15 публикация Саммари | `services/summary_generator.py`, `services/telegram_send.py`, `services/summary_scheduler.py` | `widget-map` (Сводка→Аналитика) | F6 отчёт |

## 3. Блок B/F — реестр, секреты, hidden (REQ-F8-02/03/06, R17)

- **Полнота:** `{internal_key}` реестра == `REGISTRY` == **459**; пустых ячеек — **0**; дельта **411 → 459 = 48** (`status=new`, перечислена в `.meta.md`).
- **Секреты (R17):** **28** записей (`secret=true`/`category=keys`) → во всех артефактах только `{configured,last4}`; открытых значений нет. Точки маскирования read-путей: `web/api/routes.py::_mask_secret` (269) → `/api/config` (489), `/api/config/keys/own`, `/api/config/keys/status`; `services/debug_config.py::_mask_secret` (181); `services/status_service.py::_mask_key` (54/60); `services/llm_client.py::_mask_secrets` (80).
- **hidden-контроль:** **1** скрытый ключ — `limits.factcheck_context_messages` (`ParamSpec.hidden=True`): остаётся в реестре/правах, исключён из UI-каталога (`/api/config`, `params-meta`), сохранён (не удалён).
- **api-only ≠ сохранено (REQ-F8-08):** **25** записей `ui_visibility=api-only` (env/infra-ключи без UI-места) + `api-only`-виджеты (`/api/debug/config`, `/api/health`, `ui_flags`) — помечены как «не сохранено в UI» (детали в `widget-map`).
- `visible` = **433**, `per_chat` = **358**.

## 4. Блок C/D — карты экранов и виджетов (REQ-F8-04/05/07)

- **Карта экранов:** `old_screen → param_key → new_screen (IA §4) → read_api → write_api → ui_visibility`. Инвариант «ни один параметр не без нового места»: **459/459** ключей имеют место, «без места» = **0**; `registry-only` (неизвестных каталогу) = **0**.
- **Новая IA §4:** `Модули` (13 mod_*), `ИИ` (llm_providers/prompts/smart_cache/people_names), `Память` (memory_rag/relations/chat_lore), `PERMsoc` (permsoc); `Справка` — content-info; `.env (инфраструктура)` — 25 env-only ключей (by design, вне UI, `api-only`).
- **Карта виджетов:** виджеты §11–§21 (сон, граф, мониторинг интеллекта, лента досье, логи, превью карты LLM-вызовов, бюджеты, аналитика и т.д.) → реальные `data_source` (`web/api/*`), новое место и сохранённые действия. `api-only`-виджеты выделены отдельной секцией.

## 5. Блок E — сохранность конфигурации (REQ-F8-09/10/11)

- **Точка отката (T-2964):** git-тег `pre-round1025-f8` (@ `a40f244`) + `var/backups/f8-round1025-20260923-044606/` + `.env.bak.round1025-f8` (R18: ничего не удалено).
- **Механизм:** переиспользован существующий (`manage.py`, `var/backups/`, `.env.bak`); новый бэкап **не строился**.
- **Diff:** `tools/config_snapshot_diff.py` (read-only, вне рантайма) — классификация по ключам (`pg_key`/`chat_id`), R17-safe; **8 срезов**: глобальная, чаты, ЛС, PERMsoc, промпты, модели, подключения, роли/разрешения. Отчёт: `plans/reports/round1025_f8_config_diff.md`.
- **Результат:** **0 незапланированных изменений** (read-only enabler; значения не менялись).
- **Скрытые миграции:** Δ DDL = **0**, Δ каталога = **0** (маркер-тесты F8).

## 6. Блок H — регресс и инварианты (REQ-F8-11)

| Инвариант | Проверка | Итог |
|---|---|---|
| Δ DDL = 0 | `services/pg_db.py` не менялся (freeze-hash) | ✅ |
| Δ каталога = 0 | `services/param_catalog.py` не менялся (freeze-hash); 459/98/96/21/418 | ✅ |
| Роуты `web/api/routes.py` не изменены | freeze-hash + freeze-множество 31 маршрута | ✅ |
| `APP_VERSION` не бампнут | `== 2.58.15` | ✅ |
| read-only | нет импортов `tools/*` из `services`/`web`/`handlers`; нет новых рантайм-эндпоинтов | ✅ |
| R17 | открытых секретов в артефактах нет (скан по значениям Settings/env) | ✅ |
| CSP / zero-build | нет правок `web/**`; новых внешних ресурсов нет | ✅ |

## 7. Deploy / версия (D5/D7)

- **Deploy: NOT_APPLICABLE** — F8 не меняет рантайм (`services/**`/`web/**`/`handlers/**`), БД, каталог, ассеты; `tools/*` рантаймом не импортируются. Прод-`git pull` поведение не меняет. (Оформление вердикта — `deployment.md`, T-3019 @DevOps.)
- **`APP_VERSION` = 2.58.15** (без бампа: ассеты не менялись → cache-bust не нужен).

## 8. Артефакты F8 (additive)

- `plans/docs/param-registry-round1025.tsv`
- `plans/docs/param-registry-round1025.meta.md`
- `plans/docs/screen-map-round1025.md`
- `plans/docs/widget-map-round1025.md`
- `plans/reports/round1025_f8_config_diff.md`
- `tools/gen_param_registry_round1025.py`, `tools/config_snapshot_diff.py`
- тесты: `tests/test_round1025_f8_registry.py` (+ фикстуры freeze)
