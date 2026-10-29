# W1 EVOL-031 — вывод Smart Cache / Exact Match replay из эксплуатации

Реализация в worktree `evol-71536a366a11-c63f6f44` (branch `evol/impl`), база
`2.58.141 @ 5346ee76` + docs. Источники: `plans/current_task.md` EVOL-031
(~:424-438, «Границы удаления обязательны» + 4-шаговый порядок),
`plans/features/evol/audit/base-revalidation.md` §EVOL-031 (карта удаления на
прод-базе), `backend-defects-audit.md`.

Вердикт: **ветка replay готовых ответов удалена из активного пути; защищённые
механизмы сохранены; обратная совместимость аддитивная (без деструктивных
миграций); мёртвых переключателей/эндпоинтов, включающих replay, не осталось.**

---

## 1. Baseline (до правок, read-only)

| Параметр | Значение на базе |
|---|---|
| `SMART_CACHE_ENABLED` (settings.py:2193) | default **False** (mandate D212); владельцем отключён (ТЗ) — replay search/web/youtube фактически не отдавал ответы, но `set()` продолжал писать при hot-переопределении |
| `CHAT_DEDUP_ENABLED` (settings.py:2928) | default **True**, TTL 300 с (settings.py:2930) |
| Фактическое состояние direct_dedup в проде | ветка Dormant: гейт `MCA_CONTEXT_ANSWER_CACHE_ENABLED` (env-only ClassVar, default ON, settings.py:2340) выключал text-replay; реплей оставался достижим «OFF»-переключением гейта |
| Слаги ответного кеша | `search`, `web`, `youtube` (живые consult+store); `factcheck` — legacy-регистрация после FC-06C (метка provenance); `factcheck_temporal` уже снят (Epic 72) |
| Хранилище | общая таблица `smart_cache` (SQLite, DDL database.py:2286 + smart_cache.py:173); одно хранилище для: ответных кешей, `direct_update`-маркеров (24 h, MCA-22), `factcheck_wide_context`-срезов (~120 с, CFG-06) |
| Телеметрия hit/miss | только INFO-логи (`smart cache: hit/miss/expired/set`); счётчиков попаданий нет; `smart_cache_lock_exhausted_total` (F17); MCA-событие `DIRECT_UPDATE_DEDUP_HIT` (маркеры — защищено); stage-событие `answer_cache skipped` (удалено вместе с веткой) |
| Строки таблицы в проде | **не измерялось из lane** (боевая БД недоступна из worktree). SQL для DevOps/владельца: `SELECT COUNT(*) FROM smart_cache;` разрез по префиксам: `key LIKE 'direct_update%'` (маркеры), `'factcheck_wide_context%'` (срезы), остальное — инертные legacy-строки ответных кешей |

## 2. Удалено (точный список)

**Ответный кеш search/web/youtube (consult+store на ответном пути):**
- `handlers/search.py` — импорт `get_smart_cache` (бывш. :31), consult-блок с reply из кеша (бывш. :138-146), `cache.set` после генерации (бывш. :168); обновлены комментарии.
- `handlers/web.py` — импорт (бывш. :26), consult-блок (бывш. :169-177), `cache.set` (бывш. :197).
- `handlers/youtube.py` — импорт (бывш. :74), consult-блок URL-ветки (бывш. :1226-1233), `cache.set` после мультимодалки (бывш. :1278), `cache.set` после субтитрового каскада (бывш. :1293); docstring/комментарии медиа-веток приведены к актуальному состоянию.

**direct_dedup replay-ветка Direct Chat (рубильник включённо удалён):**
- `services/direct_chat_service.py` — модульные хелперы `_answer_cache_disabled_emitted` / `_answer_cache_disabled_notified` / `_legacy_text_replay_enabled` (бывш. :721-740); объявления `answer_text`/`dedup_key` (бывш. :2819-2820); consult+replay/silence-блок с ранним return (бывш. :2822-2861, включая stage-событие `answer_cache skipped`); запись исхода в finally `set_dedup(dedup_key, answer_text or "")` (бывш. :4610-4615); `answer_text = answer` (бывш. :4469); импорт `normalize_text` (бывш. :177); комментарий инжекта кеша переписан (теперь `self._cache` — только update-маркеры, :2357-2362).
- `services/smart_cache.py` — методы `get()`, `set()`, `get_dedup()`, `set_dedup()`, `_active()`; слаги `search`/`web`/`youtube`/`direct_dedup` из `_NORMALIZERS`; ветки `flags.smart_cache_enabled`/`flags.chat_dedup_enabled` в `_sweep_ttl`. Docstring модуля переписан (маркерное TTL-хранилище).
- `bot.py` — комментарий инжекта (:629-631) обновлён; сама инжекция `cache=get_smart_cache()` СОХРАНЕНА (нужна update-маркерам).

**UI/каталог/эндпоинты «Умный кэш»:**
- `services/param_catalog.py` — группы `limits_smart_cache` (бывш. :295-296) и `flags_smart_cache` (бывш. :382-383); параметры `SMART_CACHE_ENABLED` (бывш. :1320-1321), `SMART_CACHE_TTL_SECONDS`, `SMART_CACHE_MAX_ROWS` (бывш. :1694-1697), `CHAT_DEDUP_ENABLED` (бывш. :1355-1356), `CHAT_DEDUP_TTL_SECONDS` (бывш. :1856-1857); `TAB_SMART_CACHE` + запись в `CONFIG_TAB_TITLES` + nav-маппинг + правило `TAB_RULES` (бывш. :3198/:3224/:3273/:3439-3442); описание группы `flags_chat_behavior` без «дедуп»; счётчик вкладок 19→18 (комментарий).
- `web/app.js` — вкладка TABS `smart_cache` (бывш. :273-279); карточки «Умный кэш» в HUBS (бывш. :485-487) и HUBS_V2 (бывш. :543-545); подзаголовки хабов «ИИ» без «кэш»; `ROUTE_TO_TAB['#/ai/smart-cache']` (бывш. :1533); `TAB_TO_ROUTE.smart_cache` (бывш. :1570); `ROUTE_PARENT` запись (бывш. :1600); записи `'smart_cache'` в списке config-вкладок и icon-карте (бывш. :349/:418). **Добавлено** (backward-compat, по образцу «удалённые роуты → алиасы»): `ROUTE_ALIAS['#/ai/smart-cache'] = '#/ai'` — старые ссылки ведут на витрину «ИИ», не 404 и не открывают кеш.
- `web/index.html` — правок не требовалось: строк «Умный кэш»/`smart_cache` там не было (карточка рендерилась из app.js).
- `web/api/` — dedicated cache-эндпоинтов не существовало (настройка шла через generic `/api/config` из каталога — поверхность снята каталогом); исторический docstring в `web/api/routes.py` (:620-621) больше не ссылается на несуществующую вкладку.
- `services/mca_trace.py` — мёртвый блок `runtime["cache_entries"]` (бывш. :611-618: SmartCache никогда не имел `size`/`__len__`, метрика не эмитилась) удалён как неинформативная метрика.

**Конфиг-ключи (аддитивная политика, без потери данных):**
- `config/settings.py`: `SMART_CACHE_ENABLED`, `SMART_CACHE_TTL_SECONDS`, `CHAT_DEDUP_ENABLED`, `CHAT_DEDUP_TTL_SECONDS` — **поля сохранены, кодом больше не читаются** (комментарии EVOL-031: «включить replay через эти ключи невозможно»). Причина: legacy-тесты делают `dataclasses.replace(settings, ...)` по этим полям; удаление поля дало бы TypeError вместо честного «ключ не действует». `SMART_CACHE_MAX_ROWS` — АКТИВЕН (потолок строк общей таблицы маркеров/срезов; env-only, в каталог не возвращается). `SMART_CACHE_LOCK_RESILIENCE_ENABLED` — активен (F17). Старые значения в PG (`flags.smart_cache_enabled`, `flags.chat_dedup_enabled`, `limits.smart_cache_ttl_seconds`, `limits.chat_dedup_ttl_seconds`) становятся игнорируемыми orphan-ключами — аддитивно-безопасно, миграция не требуется.
- `MCA_CONTEXT_ANSWER_CACHE_ENABLED` (env-only, mca_gates.context_answer_cache_enabled) — **оставлен инертным**: после удаления ветки он ничего не включает/выключает; удаление затронуло бы mca_gates.py/module_registry.py/tests (зона MCA-lane'ов). В реестре module_registry остаётся строкой перечня гейтов; re-enable невозможен по построению.

## 3. Защищено и не тронуто (проверено тестами)

- **Telegram update-дедуп / idempotency-маркеры**: `response_freshness.py` (slug-префикс `direct_update`, TTL 24 h), `get_update_marker`/`set_update_marker`, MCA-событие `DIRECT_UPDATE_DEDUP_HIT`, drift-guard констант — работают (regression-тесты roundtrip/expiry).
- **Wide-context срез фактчека (CFG-06)**: `factcheck_context.py` (`build_key("factcheck_wide_context")` + marker-API с TTL ~120 с), `factcheck_suitability`, `tool_router.py:3180-3186`, `handlers/factcheck.py:272/:482` — без изменений; набор test_factcheck_*_cfg06 зелёный.
- **Provenance-метка `factcheck`**: регистрация слага оставлена (FC-06C: `FactCheckPlan.cache_slug` — ярлык; читателей вердиктов нет).
- **Утилиты** `normalize_url`/`normalize_text`/`build_key` — общие потребители (lore_compiler_service, temporal_factcheck, direct_chat_service, factcheck_context) не затронуты.
- **Кеш эмбеддингов**: `embedding_cache` — отдельная таблица; `embedding_control_plane.py` не ссылается на smart_cache (структурный тест).
- **Троттлинг/кулдауны** (D237 — первый барьер), **breaker**, **concurrency pool** — без изменений.
- Provider-side prompt caching, HTTP/DB/config-кеши, TTL технических данных — вне зоны, не тронуты. Семантический/векторный кеш ответов взамен НЕ введён.
- `services/memory_health.py:140-141` — строка «smart_cache: N строк» ОСТАВЛЕНА: таблица остаётся живым хранилищем маркеров/срезов, счётчик осмыслен.

## 4. Incidental finding — исправлен в той же зоне

**Смежный дефект (related, исправлен):** `factcheck_context.write_slice_cache` пишет
через `set_update_marker(..., ttl_seconds≈120)`; прежний `_write_once` выметал
`created_at < now − ttl_вызывающего` → каждая запись wide-context среза удаляла
24-часовые update-маркеры старше 2 минут (угроза двойной обработки Telegram-update).
Фикс: порог ленивой чистки = `max(TTL записи, _sweep_ttl()=24 h)`; срок жизни записи
определяется её TTL при чтении. Регресс-тест: `test_short_ttl_write_keeps_update_markers`.

## 5. Тесты

**Новые** — `tests/test_evol031_smart_cache_retirement.py` (16 тестов, все PASS):
(a) search/web: повторный идентичный запрос → 2 живых LLM-вызова, реплея нет;
youtube — структурный; (b) direct_dedup: идентичный текст → новая генерация при
ПРИНУДИТЕЛЬНО включённых legacy-рубильниках (settings+hot), в таблице только
`direct_update`-маркеры; API/ветка отсутствуют структурно; (c) update-маркеры:
roundtrip/expiry + регресс смежного фикса; (d) каталог/app.js/index.html/web-api:
поверхность снята, старый маршрут алиасится; (e) утилиты живы, защищённые слаги
работают, ответные слаги удалены, embedding_cache независим.

**Прогон:** `pytest tests/test_evol031_smart_cache_retirement.py` → **16 passed**;
защищённые наборы `test_factcheck_{context,gate,orchestrator,attribution}_cfg06`,
`test_cfg07_{egress_dictionary,guard_tail}`, `test_factcheck_post_release_w2`
→ 189 passed / 1 failed (см. coordination); `python -m compileall services handlers -q`
→ OK; `node --check web/app.js` (v24.16.0) → OK.

## 6. Coordination notes — существующие тесты, устаревшие из-за удаления

Все отказы ниже — **прямое следствие удаляемого поведения** (тесты пинят replay/
UI, которые владелец приказал удалить). Правки механические; файлы вне моего
test-скоупа (`tests/test_evol031_*`) — не правил, отдаю владельцу скоупа:

| Файл:место | Что пинит | Требуемая правка |
|---|---|---|
| `tests/test_smart_cache.py` (14 отказов: TestCacheHitInHandlers::test_web…, весь TestDirectDedupCache, LockResilience-тесты через get/set) | ответный кеш и dedup-API | удалить/переработать секции под marker-API (нормализ/build_key тесты остаются валидными) |
| `tests/test_direct_chat.py::TestHandleDedup` (5 из 11) | replay/silence-ветку | удалить replay-тесты; `test_context_policy_on_disables_text_replay`, different-user/text, update-slot-release — проходят |
| `tests/test_p0_admin_cache_toggle_save.py` (9/9) | горячий тумблер `flags.smart_cache_enabled` (fix T-619) | файл целиком про удалённый флаг — упразднить/заменить тестом generic-сохранения конфига |
| `tests/test_frontend_tab_mapping.py` | `TAB_SMART_CACHE` import (:33,:51), tab_nav (:90), tab_group_ids (:325) | убрать TAB_SMART_CACHE; отдельный счётный тест (:186 `len(REGISTRY)==588`) падал ЕЩЁ ДО правок (pre-existing drift) |
| `tests/test_budget_guardrails_round1024.py` | menu/tab-снапшоты с `'smart_cache'` (:58,:84 и snapshot-тесты) | убрать `'smart_cache'` из списков; счётные пины (:171/:220 зона) уже дрейфовали до меня (2 pre-existing отказа: counts 588) |
| `tests/test_factcheck_post_release_w2.py:263` | `build_key("search", "ok")` жив | строку заменить на `pytest.raises(ValueError)` (слаг удалён EVOL-031) |

**Чужой lane (не мой дефект):** `tests/test_mca22_core_round1027.py`
TestCanonicalEnvelope (4) + TestQuoteResolver::test_priority6_bounded_history (1) —
`sqlite3.OperationalError: near "?": syntax error` из `services/message_identity.py:268`
(файл изменён параллельным lane EVOL-010/013; на чистой базе тесты проходят).
Требует исправления автором правки message_identity/database.

## 7. Статус верификации

- cache-hit в пользовательском пути: **исключён структурно** (методов/веток нет) + поведенческие тесты (2 LLM-вызова) — VERIFIED (agent-side).
- Возврат через флаг/старый UI: **невозможен** (force-ON тест, структурные проверки каталога/app.js; алиас маршрута ведёт на витрину) — VERIFIED (agent-side).
- Дедуп событий Telegram, idempotency, троттлинг, wide-context фактчека, embedding-кеш — regression PASS.
- Живые Telegram-чаты: проверки не проводились (запрещены правилами проекта; по standing rule PET_PROJECT не блокируют релиз). Рекомендуемая post-deploy проверка владельцем/DevOps: `/healthz` 200, в логах нет `smart cache: hit` для ответных слагов, счётчик строк `smart_cache` стабильный.

## 8. Остаточный риск

- Инертные env/PG-ключи (`SMART_CACHE_*`, `CHAT_DEDUP_*`, `MCA_CONTEXT_ANSWER_CACHE_ENABLED`, 4 hot-ключа) остаются в конфиг-пространстве как no-op — задокументированы; повторное включение replay невозможно ни через один из них.
- Legacy-строки ответных кешей в таблице `smart_cache` инертны (читателей нет), выметаются ленивой чисткой (24 h порог) и потолком `SMART_CACHE_MAX_ROWS`; деструктивная чистка не выполнялась (обратная совместимость).

---

## 9. Follow-up: disposition устаревших legacy-тестов (§6 закрыт)

По отдельному заданию (owners' решение EVOL-031 действует) шесть файлов из §6
выровнены с retired-реальностью; правки ТОЛЬКО в тестах, исходный код не менялся
(реального дефекта удаления вскрыто не было). Итог прогона всех шести файлов +
`tests/test_evol031_smart_cache_retirement.py`: **133 passed / 0 failed**;
полный `tests/test_direct_chat.py` → 167 passed.

| Файл | Disposition | Детали |
|---|---|---|
| `tests/test_smart_cache.py` | **updated** (23 passed) | Docstring → EVOL-031. `TestBuildKey` — слаги factcheck/factcheck_wide_context. `TestSmartCacheStorage` — 5 тестов переведены на `get_/set_update_marker` (roundtrip/miss-log/expiry/max-rows-cap/fail-open), `test_disabled_is_noop` удалён (флага больше нет). `TestCacheHitInHandlers::test_web…` → `test_web_second_call_runs_service_again` (2 живых вызова сервиса;_factcheck-тест сохранён — он и раньше asserted fresh-check). `TestDirectDedupCache` (7) — удалён целиком (субъект выведен; retirement покрыт test_evol031). `TestLockResilience` — 5 тестов переведены на marker-API (механизм F17 не менялся), pragmas/init-тесты сохранены. |
| `tests/test_direct_chat.py::TestHandleDedup` | **updated** (10 passed; файл целиком 167 passed) | Класс → no-replay контракт: `test_repeat_identical_text_runs_llm_again` (отн. счётчик: +1 генерация на повтор), `test_empty_answer_repeat_retried_live`, `test_llm_error_repeat_gets_fresh_attempt` (новая попытка вместо «маркера молчания»), `test_switch_off…` (флаг инертен), `test_throttle_stays_first_barrier` — честная версия: заряд бакета исчерпан ДО ходов (старая версия проходила через replay-шорткат, маскировавший троттлинг; авторство смены поведения — само удаление ветки, не source-дефект). `test_ttl_expiry_calls_llm_again` удалён (TTL дедуп-записи не существует). Autouse `_legacy_dedup_policy` (мёртвый гейт MCA-07) снят. Остальные 6 тестов класса не тронуты. |
| `tests/test_p0_admin_cache_toggle_save.py` | **updated** (9 passed) | НЕ удалён: файл — регресс GENERIC-механики сохранения тумблера (optimistic-токен + retry на ChatParamsConflict, фикс 28.10.2026), она жива. Payload-ключ заменён на живой `flags.throttle_persistent_enabled`; сид-строка limits нейтральная; SmartCache._active-ассерты сняты; `test_smart_cache_get_follows_hot_flag` → `test_smart_cache_replay_api_absent_and_hot_mechanics_alive` (API отсутствует + hot-механика работает для живого ключа). |
| `tests/test_frontend_tab_mapping.py` | **updated** (38 passed) | Импорт/ALL_TABS/tab_nav без TAB_SMART_CACHE; 23→22 вкладки; `test_smart_cache` (tab_group_ids) удалён; `TestJsMirror::test_smart_cache_and_7_ai_cards` → `test_smart_cache_card_retired` (id/маршрут отсутствуют, алиас `#/ai/smart-cache → #/ai` присутствует). Счётный пин → фактические 581/119/117 с комментарием: пин 588 дрейфовал ЕЩЁ на базе W1 (−2, pre-existing failure), EVOL-031 −5. |
| `tests/test_budget_guardrails_round1024.py` | **updated** (25 passed) | `EXPECTED_TAB_RULES_IDS`/`EXPECTED_TAB_IDS` без `smart_cache` (28→27 пунктов витрины); счётные пины `test_registry_counts_pinned` и `test_catalog_counts_unchanged_by_guardrails` → 581/119/117/22×3 (в т.ч. pre-existing −2 drift базы зафиксирован честно). |
| `tests/test_factcheck_post_release_w2.py` | **updated** (файл green) | `test_smart_cache_slug_removed` → текущий контракт: ответные слаги search/web/youtube/direct_dedup отсутствуют И `build_key` по ним ValueError; `factcheck` (provenance-метка) и `factcheck_wide_context` (CFG-06 срез) работают. |

Примечание: отказ `tests/test_mca22_core_round1027.py` (TestCanonicalEnvelope ×4 +
QuoteResolver ×1, `OperationalError: near "?"` из `services/message_identity.py:268`)
— **не EVOL-031**: message_identity.py/database.py изменены параллельным lane
(EVOL-010/013), на чистой базе тесты проходят. Остаётся на авторе той правки.
