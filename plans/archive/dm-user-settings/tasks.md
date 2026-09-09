# Задачи: dm-user-settings (F-14)

> Раунд 10.3, пункт 4 ТЗ владельца (AC-4): личные сообщения настраиваются
> ОТДЕЛЬНО (как чаты) — юзер правит параметры/фичи/лимиты/ключи СВОИХ ЛС,
> наследование от глобальных, ЕДИНСТВЕННОЕ исключение — саммари в ЛС
> по умолчанию OFF.
> База: HEAD `d30b203` (раунд 10.2, задеплоен), pytest 4760, прод PID 454654.
> Спецификация: `spec.md` — **пересоздаёт @Architect** по KG-канону (файлы
> утрачены; дизайн зафиксирован в наблюдениях сущности `feature-dm-user-settings`).
> ⚠️ Код не пишется до spec.md. Порядок: реконы (done) → spec @Architect →
> @Builder (T-954…T-958) → @Reviewer → @Scanner → общая финальная фаза
> T-961…T-964 (ДУБЛЬ T-941…T-944, исполняется ОДНОКРАТНО после F-14).

## Рекон-база (@PM, подтверждено — переотражено из KG)

- [x] **T-945** — рекон: бот-путь ЛС. `direct_chat_service.py:517-521` УЖЕ резолвит
  `get_chat_param(chat_id=user.id)`; `llm_client._resolve_api_key_and_source`
  (317-356) работает по chat_id; `chat_keys`/`chat_usage` уже per-chat_id;
  группы <0, ЛС >0 — коллизий нет.
- [x] **T-946** — рекон: существующий слой F-7 — `chat_profiles.chat_params` JSONB
  {v:1, overrides, gates, keys, perm_overrides, meta} + `ChatParamsCache` TTL 120с +
  NOTIFY `chat_params_updated` + 409-оптимизм по `updated_at` + история
  `chat_lore_history` field='chat_params'. Всё переиспользуется БЕЗ изменений
  (MED-007/008 — не инвалидируем).
- [x] **T-947** — рекон прав: `services/roles.py::access_for` (глобальный →
  чат-грант `chat_admins`/`bot_roles` → локальный); DEFAULT_MATRIX
  (`param_permissions`): keys `[]`/`[]`, prompts `[local_admin]`×2, прочие
  `[moderator,local_admin]`/`[local_admin]`; секционный гейтинг для роли user
  (только Статус/Справка) — НЕ меняется.
- [x] **T-948** — рекон саммари-гейтов: `flags.summary_enabled` (bot.py:613-643)
  включает РОУТЕРЫ (summary_observer/summary/factcheck/search/youtube/web/checkup/
  direct_chat/voice) — трогать НЕЛЬЗЯ (умрёт весь direct chat); бегущий конспект —
  `summary_memory.get_window_messages` (1148); L1/L2-инжект —
  `direct_chat_service._build_global_context` (1702); `summary_scheduler._tick` —
  рассылка по smart-чатам.
- [x] **T-949** — рекон изоляции: PG-объекты, где ЛС-профили могли бы пролезть:
  `web/api/access.py` (CHATS_FOR_USER_SQL + /me), `services/chat_lore_store.py`
  list_active_chats (163-166)/list_active_chat_ids (170-173)/list_profiles (341-348),
  `services/oversight.py` build_summary (:32-33), `web/api/chat_lore.py` (списки),
  `web/api/gates.py` (_admin_grant_chat_ids, workers/budget).
- [x] **T-950** — рекон TMA: селектор чатов F-13 (единый, `accessChats`),
  `isChatContext`/`activeChatId`, `canViewTab` (user → read-only), ключ-поля
  `keys.*` (маск {configured,last4}), кнопка «↪ глобальное» resetChatOverride
  (index.html:574-576/679-681 — сейчас только isGlobalAdmin).

## Спецификация (@Architect — пересоздание по KG-канону)

- [ ] **T-951** — spec модель/права/профиль/API-контракты (вариант A — ПРИНЯТ):
  DM-скоуп = переиспользование `chat_profiles`/`chat_params` с chat_id=user.id;
  `is_dm_scope(chat_id) = chat_id > 0`; НОЛЬ DDL; `services/roles.py::AccessCtx.is_dm_owner:
  bool = False` (frozen dataclass — дефолт не ломает тесты-конструкторы);
  `access_for`: ветка ДО группового грант-лукапа — `chat_id == telegram_id and
  is_dm_scope` → is_dm_owner=True, rank = max(rank, ROLE_TYPE_RANK[ROLE_LOCAL_ADMIN]) = 3,
  role_chat=None, perms_chat = DM-пресет {sections: [prompts, limits, flags,
  reactions, content, memory], actions: []} (union с глобальной ролью; НЕ даёт
  group-секций; is_dm_owner — локальный срез без PG, fail-open);
  `services/access.py`: ТОЛЬКО is_dm-ветки — can_access_chat (→True), eligible_type
  (→ROLE_LOCAL_ADMIN: view [moderator,local_admin]/edit [local_admin]),
  can_edit_param (edit_roles — per_chat-ключи True, keys → False, R17/S2/S3);
  DEFAULT_MATRIX/effective_matrix/_normalize_perms/param_permissions — БЕЗ изменений;
  НОВЫЙ `services/chat_params.py::ensure_scope_profile(chat_id, *, dm, pg)`
  (INSERT ON CONFLICT DO NOTHING, паттерн chat_lore_store:45-46; DM →
  auto_enabled=false — LoreWorker не тронет, is_active=true,
  chat_params=_root_with_meta({})); ленивый вызов перед ПЕРВОЙ записью
  (post_config до set_chat_params — иначе мусорный 409 «профиля нет»; gates_put
  покрыт тем же); API-контракты §3.4 (см. T-956).
- [ ] **T-952** — spec саммари DEFAULT-OFF: НОВЫЙ `services/chat_params.py::
  chat_summary_enabled(chat_id) -> bool` — группы: `hot.get('flags.chat_running_summary_enabled',
  settings…)` байт-в-байт (старое поведение); ЛС: `get_chat_param_defaulted(chat_id,
  'flags.chat_running_summary_enabled', False)` — override→cast→False, БЕЗ
  global-фолбэка (единственное исключение из наследования). Вспомогательный
  `get_chat_param_defaulted(chat_id, key, fallback)` (override→cast→fallback);
  существующие get_chat_param/get_chat_params_full/_resolve_from_root — БЕЗ
  изменений (регресс-инвариант). Точки: S1 summary_memory.get_window_messages:1148,
  S2 direct_chat_service._build_global_context:1702, S3 summary_scheduler._tick
  (фильтр положительных id — ЛС не рассылаем; generate_and_send/manual /summary
  в ЛС сохраняются), S4 manual /summary в ЛС — работает (явный вызов), S5
  bot.py:613-643 — НЕ ТРОГАТЬ. НОВЫХ параметров каталога НЕТ (REGISTRY 383 /
  группы 71 / Settings 359 — эталон test_param_catalog); L2 гейтится вместе с L1
  (только внутри ветки summary_text); L3/GraphRAG-факты = ПАМЯТЬ, не саммари —
  не гейтятся.
- [ ] **T-953** — spec TMA (поверх F-13-AC-1): запись «Личные сообщения» в ЕДИНЫЙ
  селектор (is_dm:true, access:'dm'; при accessChats длиной 1 селектор виден и
  авто-выбран — loadAccessCtx:637-641); `isDmCtx()` = activeChatId != null &&
  accessChats.find(c => c.chat_id === activeChatId && c.is_dm);
  canViewTab DM-правило: `if (isDmCtx() && tab.type === 'config' && tab.id !== 'permsoc')
  return true` — открываются Провайдеры (модели read-only + BYOK-блок)/Промпты/
  Лимиты/Память-RAG/Реакции-Триггеры; permsoc скрыт (групповые перс-модули);
  бейдж «ЛС #{id}» в шапке; BYOK-блок виден (условие !isGlobalAdmin +
  isChatContext уже покрывает DM-владельца); кнопка «↪ глобальное»
  (resetChatOverride) — открыть для isDmCtx (сейчас только isGlobalAdmin,
  index.html:574-576/679-681); empty-state «выберите чат или Личные сообщения
  в селекторе в шапке» (index.html:519,1006); badge item.chat_source === 'chat' —
  переиспользование (текст «чат» оставить).

## Реализация (@Builder — после spec.md)

- [ ] **T-954** — роли/доступ: is_dm_owner в AccessCtx + access_for DM-ветка +
  access.py is_dm-ветки (can_access_chat/eligible_type/can_edit_param);
  ↓ критерии: свой id → is_dm_owner=True/rank=3/role_chat=None/DM-пресет; чужой → False;
  can_edit_param: per_chat-ключи True, keys→False (R17); глобальный админ в чужом
  ЛС — 403; DEFAULT_MATRIX/effective_matrix/_normalize_perms — без дифов;
  fail-open (PG down → работа локальные срез).
- [ ] **T-955** — chat_params: ensure_scope_profile (+ ленивые вызовы в DM-ветках),
  chat_summary_enabled (S1-S5), get_chat_param_defaulted;
  ↓ критерии: матрица chat_summary_enabled {группа: горячий флаг как было;
  ЛС: override→True/False, override-мусор→False, нет override→False даже при
  глобальном ON}; ensure_scope_profile идемпотентен (повтор → no-op);
  get_chat_param/get_chat_params_full/_resolve_from_root/кэш/NOTIFY/409 — без дифов;
  bot.py:613-643 — без дифов.
- [ ] **T-956** — API-контракты: GET /api/access/chats|me (фильтр chat_id>0 → skip +
  синтез DM-строки {chat_id: user.id, title «Личные сообщения», photo_file_id: null,
  is_active: true, access: 'dm', is_dm: true} для ЛЮБОГО авторизованного,
  включая global admin); GET /api/config X-Chat-Id=user.id → 200 (items per_chat-
  категорий, keys.* скрыты — канон «не global admin», models.* read-only
  global-справка, ctx.is_dm=true); POST /api/config — первый write →
  ensure_scope_profile(dm=True), models.*/keys.* → 422 (существующий гейт
  routes.py:380-388), 409-оптимизм как есть; DELETE /api/config/chat/{key} — гейт
  (is_global_admin or is_local_admin or is_dm_owner) = сброс своего override;
  GET/PUT/DELETE /api/config/keys/own — гейт +is_dm_owner (BYOK своего ЛС, chat_keys
  per-chat без DDL, R17-маска); GET /api/config/keys/status — can_access_chat
  (is_dm_owner → 200), global-поле только global admin; GET /api/chat/{id}/gates —
  is_dm_owner 200 READ (who_can_toggle='global'), PUT — 403 (гейты только global
  admin, F-10-канон); GET /api/workers/budget — без изменений (403 без грантов);
  /api/oversight/summary — без DM-строк; изоляция 6 точек (П.1 access.py, П.2
  chat_lore_store.py 163-166/170-173/341-348 WHERE chat_id < 0, П.3 LoreWorker без
  изменений, П.4 oversight.py :32-33, П.5 web/api/chat_lore.py DM → 404, П.6
  gates.py _admin_grant_chat_ids — DM-грантов не создаём, gates при DM READ-only);
  ↓ критерии: контракты из spec §3.4 — 200/403/422/404 в соответствующих кейсах;
  raw-ключи никогда (R17); глобальный админ в чужом ЛС — 403.
- [ ] **T-957** — тесты: юнит — test_chat_access.py/test_dm_access.py, test_chat_params.py
  (get_chat_param_defaulted + ensure_scope_profile + chat_summary_enabled + регресс
  кэша/NOTIFY/409), test_summary_memory.py + test_direct_chat.py (S1/S2: DM при
  глобальном ON + пустом профиле — конспект НЕ создаётся; override=True — создаётся),
  test_summary_scheduler.py (_tick positive-фильтрация + get_smart_chat_ids-фолбэк),
  test_chat_lore_store.py/test_lore_worker.py (положительные id исключены),
  test_oversight.py, test_chat_lore_api.py (DM → 404); API — test_webapp_api.py
  (chats/config 200/скрытие keys/read-only models/ctx.is_dm/POST ensure/422/
  keys-own/DELETE/403 чужого), test_webapp_gates_api.py (GET 200, PUT 403),
  test_webapp_oversight_api.py; webapp-маркеры — НОВЫЙ tests/test_webapp_dm_ui.py
  (select+DM, isDmCtx-правило, «ЛС #{», BYOK-блок, empty-state «или Личные
  сообщения»), test_webapp_nav_disclosure_ui (1 селектор), test_webapp_rbac_ui
  (без изменений); ↓ критерии: полный pytest 0 failed (4760 + ~15-25 новых).
- [ ] **T-958** — TMA (поверх F-13): «Личные сообщения» в селекторе, isDmCtx,
  canViewTab DM-правило, бейдж «ЛС #{id}», BYOK-блок, «↪ глобальное» для isDmCtx,
  empty-state; ↓ критерии: вкладки Провайдеры/Промпты/Лимиты/Память-RAG/Реакции
  открываются в DM-скоупе; permsoc скрыт; селектор виден при единственной записи;
  `node --check web/app.js` clean.

## Ревью и сканирование

- [ ] **T-959** — @Reviewer: полный ревью диффов на соответствие spec.md;
  APPROVED без блокеров (RBAC-переиспользование, R17, наследование-исключение).
- [ ] **T-960** — @Scanner: выборочный аудит фичи (roles/access/chat_params/web-api,
  тесты); находки — plans/reports/, блокеры — закрыть до финала.

## Общая финальная фаза раунда 10.3 (T-961…T-964 — ДУБЛЬ T-941…T-944, ОДНОКРАТНО после F-14)

- [ ] **T-961** (AC-6) — конфликт-проверка: полный pytest (≤300с, .venv) 0 failed;
  целевые проверки: порядок роутеров bot.py — без дифов; F-3 scam-followup
  (admin_commands.py без дифов; T-663 остаётся ОТКРЫТОЙ); param_permissions/
  DEFAULT_MATRIX — дефолты целы; кэш hot_chat (TTL 120с/NOTIFY/409-оптимизм без
  инвалидаций); SummaryScheduler (ЛС НЕ в smart-чатах); DM-команды /clear /persona
  /tone /forget — без дифов; gates/permsoc/worker_budget — не затронуты;
  `git diff --check` чист.
- [ ] **T-962** (AC-7) — README: ироничный абзац, счётчик тестов, строки версии.
- [ ] **T-963** (AC-8) — коммит master: русский conventional, grep секретов
  (R17), `git diff --check`, полный pytest.
- [ ] **T-964** (AC-9) — деплой: ssh nik@198.46.175.136 (осторожно fail2ban
  maxretry=3, пароль ИНТЕРАКТИВНО/sshpass — в планы НЕ писать R17), `git pull
  --ff-only`, .env при необходимости, `systemctl restart admin_bot`, status
  active, journal чист; live-проверка: саммари ЛС OFF по умолчанию, правка
  параметров юзером, наследование от глобальных, ключи своего ЛС (BYOK).

## Границы (НЕ трогать — diff-проверка в T-961)

- bot.py: порядок роутеров + гейт `flags.summary_enabled` (613-643) — без дифов;
- `services/access.py`: DEFAULT_MATRIX/effective_matrix/_normalize_perms/param_permissions —
  без изменений; существующие публичные функции chat_params
  (get_chat_param/set_chat_params/кэш TTL 120с/NOTIFY/409) — без изменений;
  hot_config/ConfigCache — без дифов;
- SummaryScheduler служба + generate_and_send — без дифов (фильтр только в _tick);
- DM-команды /clear /persona /tone /forget + handlers/direct_chat.py — без дифов;
- F-3 scam-followup T-663 (admin_commands.py) — без дифов (остаётся открытой);
- services/feature_gates.py + gates-канон (write — только global admin) — без изменений;
- каноны промптов / SQLite-схема / .env — без дифов; REGISTRY 383/71/359 — без изменений.

## Конфликты с активными фичами (пересечения — фиксирую в backlog.md)

- F-1 `post-deploy-admin-minors`: T-648 (атомарный POST /api/config) — тот же
  routes.py → F-14 ДО T-648; T-650 (docstring can_edit_param) — после F-14
  (функция расширяется DM-веткой); T-651/652 (унификация кастов) — учесть cast
  get_chat_param_defaulted.
- F-3 `scam-incident-security-followup`: T-663 (DM-гейты admin_commands.py) —
  та же DM-плоскость; исполнять после F-14; T-663 остаётся открытой.
- F-5 `config-read-path-audit`: новые read-пути F-14 (chat_summary_enabled/
  get_chat_param_defaulted) включить в остаточный аудит (стиль hot.get).
- F-4/F-6/F-2 — пересечений нет.
