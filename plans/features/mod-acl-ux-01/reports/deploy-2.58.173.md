# Deploy 2.58.173 — MOD-ACL-UX-01 M1, единая проверка глобального админа (ACL false-403)

Выкладка на **production** (192.255.209.205, `/var/www/admin_bot`), 09.11.2026 07:40:00 UTC.

## 1. Границы выкладки

| Поле | Значение |
|---|---|
| DEPLOY_SOURCE | `release/2.58.173` = `17c3a05e2a1a3ed59ff6f15b97d0a8d0f50445b1` |
| Кандидат на ревью | `adfd0d0c` (Reviewer APPROVED, изолированный checkout), родитель `bee14188` |
| Bump-коммит | `17c3a05e` — только `APP_VERSION`, README (rolling-строка), F8-мета, version-пины (27 файлов / 28 строк) |
| Предыдущий прод | `bee14188` @ `release/2.58.172` (ветка `3a186c01`), 2.58.172, schema 46 |
| MUTABLE_WORKTREE_REQUIRED | **no** — immutable checkout по SHA, `dirty_after=1` (только untracked `.cache/`, было и до выкладки) |
| Repo write scope | `config/settings.py`, `README.md`, `plans/docs/param-registry-round1025.meta.md`, 24 test-файла |
| Δ DDL | **0** — схема остаётся v46, миграций нет |

### Сверка дельты `bee14188..adfd0d0c`

9 файлов: `web/api/memory_agi.py`, `web/api/chat_lore.py`, новый `tests/test_mod_acl_ux_01_m1_acl_false_403.py`
(274 строки), 5 правок тестов на канонную проверку + отчёт предыдущей выкладки. `services/`, миграции,
`web/app.js`, промпты и каталог параметров вне дельты.

Суть фикса: обе локальные копии `_is_global_admin` (сравнение строки роли) заменены делегированием в
`web/api/deps.user_is_global_admin` (role_type `global_admin` / legacy-роль `admin` / wildcard);
shortcut `settings.ADMIN_USER_ID` сохранён. Число вызовов guard идентично родителю:
`memory_agi` — 20, `chat_lore` — 5 (1 положительная + 4 отрицательные ветки).

## 2. Предрелизные прогоны (на точном кандидате)

| Набор | Результат |
|---|---|
| новый regression-тест ACL на кандидате | **17 passed** |
| тот же тест на родителе `bee14188` | **4 failed / 13 passed** — `assert 403 == 200` (false-403 воспроизведён) |
| memory API + chat_lore + access/roles/deps (14 файлов) | **298 passed** |
| webapp-наборы (63 файла) | **1457 passed, 14 failed** — все 14 падают **так же на родителе** (предсуществующие снимки UI/ассетов) |
| memory-подсистема `-k "memory or acl_ux01"` | **1247 passed, 1 failed, 1 error** — предсуществующие, воспроизведены на родителе (1 failed, 18 errors) |
| version-пины + bump-сверка (24 пина + новый тест) | **877 passed** |
| F8-каталог `gen_param_registry_round1025.py --check` | `CHECK OK: реестр 606 == REGISTRY, R17-чисто` |

Предсуществующие падения (воспроизведены на родителе, к дельте не относятся):

- `test_webapp_*` — 14 кейсов статических снимков навигации/ассетов (напр. ожидание 15 модулей при 16).
- `test_speech_p0_a2_memory.py::TestSelfEchoNotFactual::test_style_anchors_not_broken`
  (`AnchorsDB` без `get_active_participants` — неполный тест-дубль).
- `test_youtube_multimodal_download_round1024.py` — errors setup: `handlers.youtube` без `get_smart_cache`.

## 3. Выкладка

- Снапшот `/tmp/predeploy-258173.db`: SQLite backup API с read-only источника, `user_version 46`,
  `schema_migrations 35`, `mca_lessons 8`, `quick_check ok`, 1 850 130 432 B,
  sha256 `a22f8205108cc781d892c37e4b8a4c7bfa28a72cc4215a162c5b153eab07df04` (read-back на снапшоте совпал с живой БД).
- `git fetch origin release/2.58.173` → `git checkout -B release/2.58.173 17c3a05e…`, HEAD совпал;
  на сервере `APP_VERSION = "2.58.173"`.
- `systemctl restart admin_bot` (07:40:00 UTC): `active (running)`, MainPID **3355214**, **NRestarts=0**.
- Диск после снапшота: 36G/99G (38 %).

## 4. Пост-деплой (факты с прода)

| Проверка | Факт |
|---|---|
| `/healthz` локально (127.0.0.1:8000) | `{"status":"ok","version":"2.58.173"}` |
| `/healthz` публично (`admin-bot.duckdns.org`) | 200, `2.58.173` |
| Unit | `active (running)`, MainPID 3355214 (тот же), NRestarts=0 |
| Схема | `user_version 46`, `schema_migrations 35`, head `46`, `quick_check ok` |
| Миграции при старте | `migrations: start | current user_version=46 | pending=[]` → строгий no-op |
| Журнал | `Traceback` с 07:40:00 — **0**, error-level — **0** |
| Served asset | `web/app.js` sha256 `e6fdef1f…2291` (2 082 497 B) = файл в репозитории на выложенном SHA |
| Mini App shell | `GET /web/` → 200, 1 288 955 B |
| `chat_lore` startup ensure | `inserted=0, skipped=2` (без ошибок) |

Побочное наблюдение (не связано с дельтой): в **старом** процессе (pid 3337241) в 07:39:39 и 07:39:44
два WARNING-трейсбека `services.meme_initiative` → `sqlite3.OperationalError: database is locked`
(`[meme] attempt journal failed`), по времени совпадают с чтением БД для снапшота; путь fail-soft,
в новом процессе повторов нет. Кандидат на отдельный бэклог, релиз не блокирует.

## 5. Живая проверка ACL (read-only, без имперсонации владельца)

| Запрос | Ответ |
|---|---|
| `GET /api/memory/stats` без initData | **401**, `{"detail":"missing init data"}` |
| `GET /api/memory/embeddings` без initData | **401** |
| те же эндпоинты с битым `X-Telegram-Init-Data: bogus=1` | **401** (не 403) |
| контроль: `GET /api/memory/definitely-not-a-route` | **404** — маршруты не «ловятся» общим обработчиком |
| маршруты в коде | `@memory_router.get("/memory/stats")` (стр. 1044), `("/memory/embeddings")` (стр. 479) |

Проверка владельца с настоящим Telegram initData агенту недоступна (имперсонация запрещена) —
см. §6.

## 6. Что осталось проверить владельцу

1. Открыть в Mini App (под своим Telegram ID) **Vector Memory** и **Embeddings** — ожидается 200 и данные,
   без «Доступ запрещён».
2. Второй, не-админский аккаунт: те же экраны должны по-прежнему показывать отказ (403).
3. Локальный админ чата и модератор — доступ к памяти не появляется (только свои чаты в лоре).

## 7. Откат

- Код: `git checkout -B release/2.58.172 3a186c01 && systemctl restart admin_bot` (код = 2.58.172 `bee14188`).
- Данные: снапшот `/tmp/predeploy-258173.db` (sha256 сверху) — нужен только при повреждении данных;
  Δ DDL = 0, поэтому схема отката не требует.
- Mutable-checkout на сервере не требуется, повторный деплой возможен по любому из SHA.
