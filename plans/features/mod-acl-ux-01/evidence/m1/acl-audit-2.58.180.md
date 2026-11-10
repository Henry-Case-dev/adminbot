# M1 — ACL, секреты, 503 и реальный отказ на выкаченной сборке 2.58.180 (721bab10)

**Сборка.** `2.58.180` @ `721bab10` (`721bab1000a36c55b59794c36b6aefa6322a367c`, ветка `release/2.58.180`; `e63eb64c` добавляет только релизную запись — `git diff --name-only 721bab10 e63eb64c` = один файл в `plans/`). Артефакт выкладки = этот SHA: `plans/features/vmq-onto-01/evidence/vmq-q1/release-2.58.180.md`. Живая сверка: `GET /healthz` → `{"status":"ok","version":"2.58.180"}`.
**Метод.** Код читался только через `git show 721bab10:<path>` (главный worktree — другая линия, HEAD ≠ прод). Продуктовый код не менялся. Ниже — префиксы блоб-хешей процитированных файлов.
## 1. Инвентарь admin/global-admin проверок в `web/api/*`
| # | Проверка (файл:строки, blob) | Предикат | role_type? |
|---|---|---|---|
| 1 | `web/api/deps.user_is_global_admin` 207–222 `8ea42e1c` | `perms.wildcard or role_type_of(...)=="global_admin" or role=="admin"` | **ДА** + legacy-строка |
| 2 | `deps.requires_global_admin()` 225–237 | обёртка над (1); 40 эндпоинтов | ДА |
| 3 | `deps.requires_permission(s)` 190–204 | `match_permission(perms, required)` | **НЕТ** (только permissions) |
| 4 | `services/roles.role_type_of` 88–96 `14788c83` | колонка `role_type` → иначе `role_name=="admin"`→`global_admin` → иначе `custom` | ДА |
| 5 | `services/roles.access_for` 144–215 | `role_type=="global_admin" or perms.wildcard` → поле `AccessCtx.is_global_admin` | ДА |
| 6 | `AccessCtx.is_global_admin` в `access.py`(9)/`gates.py`(4)/`routes.py`(22)/`anticliche.py`(1) | поле из (5) | ДА |
| 7 | `routes._ctx_global_admin` 365–367 `9e88bfd8` | (5); 11 вызовов | ДА |
| 8 | `routes._is_global_admin` 2713–2730 (F11) | локальная копия (1), fail-closed; 1 вызов — `/api/status/logs` | ДА |
| 9 | `memory_agi._require_global_admin` 167–184 `a6ac54e7` | (1) + `settings.ADMIN_USER_ID`; 32 эндпоинта (`memory_agi`20, `anticliche`6, `cognitive_map`2, `initiative_vitality`2, `memory_overview`2) | ДА |
| 10 | `anticliche._require_global_admin` 53–58 `02d84a6f` | (5), своя обёртка | ДА |
| 11 | `chat_lore._is_global_admin` 159–169 + `can_access_chat` 172–177 `2e020112` | (1)+`ADMIN_USER_ID`, затем строка `chat_admins` | ДА |
| 12 | `cover_styles._viewer_is_admin` 189–194 `84da4899`; `stories._require_memory_editor` 81–85 `6e2bbd8a`; `summary_test._chat_accessible` 190–202 `bf6d7f6c` | (1)/(5), fail-closed | ДА |
| 13 | `routes._prompt_hidden_admin` 3944–3947, `_persona_can_view/edit` 3307–3345, `speech._can_edit_*` 364–401 | (1)/(5) + per-ключевые права | ДА |
| 14 | `services/debug_config.is_debug_admin` 162–180 `954acca9` | `cache.admins()` + `wildcard`/`action.debug.config`, фолбек `ADMIN_USER_ID` | **НЕТ** |
| 15 | `services/chat_access.is_admin/privilege` 43–64 `6a40dffe` | `telegram_id==ADMIN_USER_ID` или `role=="admin"` | **НЕТ** (только строка) |
| 16 | `services/access.can_access_chat` 69–79 `2e70f6d3` | по `AccessCtx`; DM-скоуп — только `is_dm_owner` | ДА (через ctx) |
## 2. Паритет путей по роутерам
**Через канонический role_type-aware предикат** (счёт эндпоинтов по `@*_router`-декораторам на 721bab10): `access.py` 8 (5); `gates.py` 3 (5); `chat_lore.py` 23 (11); `memory_agi.py`+`memory_overview.py`+`cognitive_map.py`+`initiative_vitality.py` 26 и `anticliche.py` 6 (9)/(10); `analytics.py` 10 + `analytics_viz.py` 2; `oversight.py` 8 + `oversight_router.py` 3; `summary_test.py` 6; `cover_styles.py` 6 + 6 внутри (`_viewer_is_admin`); `stories.py` 5; `speech.py` (через `_persona_access`→5); `routes.py` 5 (`requires_global_admin`) + 11 (`_ctx_global_admin`) + 22 (`ctx.is_global_admin`) + 1 (F11). `initiative_publications.py` 2 и `mechanism_diagnostics.py` 1 — `_require_chat_access` (5)+`can_access_chat`: это чат-скоуп, не глобальный гейт.
**Остались на другом предикате, с причиной:**
- `requires_permission('access'|'edit_info'|'action.*')` — 33 эндпоинта (`routes.py` 17: `/admins`, `/roles*`, `/info*`, `/control/*`, `/debug/config`; `cover_styles.py` 16): resource-модель 84.14.2 и разделение чтение↔запись↔side-effect. **Граница:** `role_type` этот предикат не смотрит; `role_type=global_admin` проходит лишь потому, что сид-роль `admin` несёт `{"wildcard": true}` (`services/pg_db.py` 630–632 `00c64133`). Роль с `role_type=global_admin` без `wildcard`/`access` получит 403 на `/api/admins`, `/api/roles`, `/api/cover/*` — тот же класс, что M1, но на permission-фронте; владелец не затронут (сид = wildcard).
- (14) `is_debug_admin` и (15) `chat_access.is_admin` — без `role_type`; (15) используется только bot-side (`direct_chat_service.py` 11777/11807, `mca_style_scope.py` 428–429) → там идентичность `role_type=global_admin` с иным именем роли считается `user` (расхождение HTTP↔чат, важно для MAC-S4-174).
- `avatars.py` 1 эндпоинт (`GET /api/avatar/{kind}/{tid}`) — только TMA-auth, без админ-предиката: фото любого `tid` по id.
**Два расхождения внутри канона:** (а) (1) принимает `role=="admin"` даже когда колонка `role_type` иная, (5) — нет (направление looser); (б) `ADMIN_USER_ID` даёт доступ в (9)/(11)/(14), но не в (2)/(5)/(8).
**Ни одного** эндпоинта в `web/api/*`, где глобальный гейт сравнивал бы только legacy-имя роли, не осталось. Websocket/SSE на 2.58.180 отсутствует (`app.js:35019` — только polling 15 с).
## 3. Секреты: где значение могло бы утечь и что этому мешает
| Путь | Механизм (не обещание) |
|---|---|
| `GET /api/config` | секрет-ключи → `_mask_secret` (`routes.py` 327–337, вызов 566): наружу только `{configured,last4}` для всех ролей, включая wildcard; keys-секция вырезается для не-глобала (543/554) |
| `GET /api/config/overrides-map`, `/config/keys/status` | тот же `_mask_secret` (1856 / 1676) |
| `GET /api/status` | `status_service._mask_key_for_role` 55–70 `81532b14`: админ `{configured,last4}`, остальные `{configured}` |
| `GET /api/status/key-history` | allowlist-payload (`routes.py` 2595–2610): модуль/провайдер/`http_status`, без ключей и `last4` |
| `GET /api/status/logs` | только глобальный админ (F11); записи кольца маскируются при записи: `SecretMaskFilter` (`bot.py` 166 `02e186f3`) → `log_ring.sanitize` 65–91 `3dba11ac` (литеральные секреты каталога, Bearer/`sk-`/URI-creds regex) |
| `GET /api/debug/config` | `debug_config._mask_secret` 181–185 `954acca9` |
| запись ключей (`POST /api/config`, `/config/keys/own`) | ответ — маска `chat_keys.mask_key_info` 74–87 `670245e1`; сырое значение отдаёт только `get_chat_key` сервисам |
| ошибки провайдеров | `llm_probe.sanitize_error` 149–158 (вырезает переданный ключ, обрезает), `llm_client._mask_secrets` 81–100, `safe_fetch.mask_url/sanitize` 117–149, `youtube_transcript_engine.mask_proxy_endpoint` 132–149 |
| лог non-2xx | `web/request_status.py` `eaabba43`: только `method`/шаблон `path`/`status`/`user`/allowlisted `reason`; `HTTPException.detail` не пишется никогда (`_emit`) |
| регресс-утверждения | `tests/test_byok_image_key_round1024.py` `bdd4e362` — `assert "brand-new-image-key" not in resp.text`; `tests/test_chat_keys.py` `1d1d8a98`; `tests/test_debug_config.py` `b58546ca` |
Граница: сплошного DOM/HTML-скана в этом аудите не было; статика значений не содержит, `/api/me` отдаёт только bool-флаги.
## 4. Аналитика / надзор
`analytics.py` (10 эндпоинтов, `b69a7734`), `analytics_viz.py` (2), `oversight.py` (8, `97695358`), `oversight_router.py` (3) используют **`requires_global_admin()`** → (1), а **не** `requires_permission` (на этих путях он не встречается ни разу). Идентичность `role_type=global_admin` проходит: колонка читается в `cache.roles()[role]["role_type"]` (`services/config_cache.py` 290/308 `5461395e`), `role_type_of` возвращает её без эвристик.
**Следствие:** причина PENDING у `MAC-S4-161`/`MAC-AC-06` («аналитика идёт другим механизмом `requires_permission`») на 2.58.180 **не подтверждается** — механизм тот же; открытым остаётся только живое открытие с реальной сессией global admin.
## 5. Различение 503 vs 403
Backend: `memory_agi._db_or_503` 186–193 `a6ac54e7` → `503 "база памяти недоступна (не инициализирована)"`; `access._require_pg` 69–71 `d29119da` и `chat_lore._pg_guard` 191–193 → `503 "PostgreSQL недоступен (R6)"`; `gates.py:63`. У 403 всегда другой `detail` (`permission denied`, `нет доступа к чату`, `только для глобального админа`).
UI (`web/app.js` `e75158f0`): общий `api()` 10658–10671 — 401 → `authError` «Не удалось авторизоваться (initData)…», 403 → toast «Доступ запрещён: <detail>», 503 не сводится к «нет доступа». Адресно: 24163–24172 (403 → «Нет доступа к параметрам этого чата…», **503 → «PostgreSQL недоступен — попробуйте позже.»**), `errText` 36858 (**503 → «История временно недоступна: …»**, 403 → «Нет прав на это действие.»), 30427 («Воркер сна недоступен (503)»), панель Embeddings 11858–11866 (403/401/сеть различаются).
Граница: где отдельной ветки нет — показывается `detail` сервера (текст разный); живой экран с искусственным 503 не поднимался.
## 6. Реальный отказ (наблюдение)
Пробы 2026-11-10 21:10 +12:00, только чтение, без заголовков авторизации:
| Запрос | Статус | Тело |
|---|---|---|
| `GET /healthz` | 200 | `{"status":"ok","version":"2.58.180"}` |
| `GET /api/memory/stats` | **401** | `{"detail":"missing init data"}` |
| `GET /api/admins` | **401** | `{"detail":"missing init data"}` |
| `GET /api/no-such-route-xyz` | 404 | `{"detail":"Not Found"}` |
Причина 401 — `deps.get_tma_user` 91–95: `request.state.tma_deny_reason="missing_init_data"` и `detail="missing init data"`; тот же запрос даёт строку `[api-status] … status=401 user=- reason=missing_init_data`. Наблюдение доказывает: на выкаченной сборке auth-слой отвечает 401 и не маскируется под 403, а 404 отделён от обоих. Live-403 не получен: нужна валидная HMAC-подпись сессии не-админа, имперсонация запрещена — это и есть ограничение `MAC-S10-12`/`MAC-S15-10`.
## Итог
M1 AUDIT COMPLETE — артефакт: `plans/features/mod-acl-ux-01/evidence/m1/acl-audit-2.58.180.md`. Координатору: карта ожидает по этим строкам отдельные файлы, поэтому этот артефакт надо **привязать** к строкам, а не считать их автоматически закрытыми.
**Подтверждает содержанием:** MAC-S4-169 (инвентарь §1/§2), MAC-S4-170 (read/edit/side-effect: `requires_permission` + `can_view_key_value`/`can_edit_param`), MAC-S4-172 и MAC-S10-13 (§3), MAC-S4-RPT-01 (форма и состав §1–§6), MAC-S4-173 (промпты: `_prompt_require_view/edit` 3950–4008 — `effective_matrix`+`can_edit_param` + (1) для hidden, второй ACL не вводится), MAC-S4-174 (HTTP role_type-aware; websocket/SSE нет; bot-side legacy — честное расхождение), MAC-S4-161/MAC-AC-06 в части механизма аналитики (§4).
**Не подтверждает (точная отсутствующая проверка):** MAC-S4-157 — запись уровня запроса по живому отказу владельца (request id, effective role, scope); MAC-S4-161/MAC-AC-06 — живое открытие `/api/analytics/*` с сессией global admin; MAC-S4-171 — живой экран с искусственным 503; MAC-S4-173 — сохранённая зависимость от SELF-DIAG-01; MAC-S10-11 — custom role и stale TMA; MAC-S10-12/MAC-S15-10 — живой негатив по чужому ЛС; MAC-S4-174 — tool calls и фоновые задачи (на этом релизе решает `chat_access.privilege`, legacy-строка).
