# Evidence — HOTFIX: cover style select → «save failed» (прод 2.58.42, HEAD 0b1ae9c)

Дата: 01.10.2026. Роль: Builder. Базис: master `0dc5679` (прод 2.58.42 = feat `9053fd5` + docs, ff до `0b1ae9c`).
Коммит НЕ создавался (по указанию). Чужой WIP не тронут: `plans/docs/mca-round1027-arch-frames.md`,
`plans/metrics.md`, `plans/workflow_state.md` (modified до моей сессии), untracked `node_modules/`,
`package*.json`, `extra_images/`, `.playwright-mcp/`.

## Root cause (подтверждён кодом + RED-on-pre-fix)

Симптом «save failed» — это `HTTPException(503, detail="save failed")` в `POST /api/cover/select`
(`web/api/cover_styles.py`, финальный `except Exception`), вызываемого селектором мини-аппа
(`web/app.js:7034 coverStyleSetSelection`). Не CRUD-редактирование профиля.

Гипотезы из задачи:
1. **PgDatabase-vs-raw Pool (§93) — НЕ текущий корень.** Аудит: все ~58 `registry.*` в
   `web/api/cover_styles.py` получают PgDatabase (`_pg(cache)` = `cache.pg`); `_pool_of`
   (`cover_style_registry.py:95-96`) ждёт `.pool` — контракт T-4219 чист. В
   `cover_style_jobs.py` `_pg()`/`_pool()` (:127-141) — тот же уровень. Локально
   родственный класс дефекта: «не тот объект на call-site» — в соседней границе (chat_params).
2. **Seed — исключён.** `deployment-round2.md:53`: seed-инвариант no-op, `medved_press` в PG цел;
   при отсутствии стиля роут вернул бы 404 `style not found`, а не «save failed».
3. **Permission — исключён для селекта.** `/cover/select` = `requires_permission('access')`
   (`cover_styles.py:345`), не admin (§135: мутации профилей — admin, выбор — access).

**Истинный корень — 2 дефекта в `cover_style_select`:**
- **Д-1 (503 на каждый выбор):** `chat_params.set_chat_params(...)` звался БЕЗ `pg=`
  (`chat_params.py:422-424`: `pg=None` → `pool=None` → `raise ChatLorePgUnavailable`) →
  ловился общим `except Exception` → 503 «save failed». Все остальные web-вызовы передают
  `pg=cache.pg` (`web/api/routes.py:684,980`; `web/api/access.py:447`; `handlers/chat_lifecycle.py:116`).
- **Д-2 (ложный успех при наивном фиксе):** патч был плоским ключом
  `{"prompts.summary_cover_style_id": id}`; `set_chat_params` мержит ТОЛЬКО namespaces
  (`overrides/gates/keys/perm_overrides/meta`, `chat_params.py:447-451`) — плоский ключ
  выбрасывается молча (200 без записи). Читающий путь резолвит `root["overrides"][key]`
  (`_resolve_from_root`, `chat_params.py:359`). Плюс: namespace в `set_chat_params`
  ЗАМЕНЯЕТСЯ целиком (`new_root[ns] = dict(patch[ns])`) — без read-modify-write наивный
  `{"overrides": {...}}` затёр бы все прочие per-chat overrides чата.

False-positive тест, маскировавший Д-1/Д-2: `tests/test_extra_cover_styles_api.py::test_select_per_chat`
монкипатчил `set_chat_params` целиком и закреплял неверную форму патча — §95/§122-класс слепого пятна.

## Изменённые файлы (worktree, НЕ закоммичено)

- `web/api/cover_styles.py` — `cover_style_select` (после фикса: :358-385): `pg=_pg(cache)` в
  `set_chat_params`; read-modify-write через `get_all_chat_params(chat_id, pg=pg)`; патч формы
  `{"overrides": merged}`; пустой `style_id` → `pop` ключа (честный resolve-чейн override →
  hot → default, DC-5, без хард-пина «нет стиля»); `not root` → честный 503 (fail-open {}
  `get_all_chat_params` = PG-чтение не удалось — НЕ пишем пустой overrides поверх чужих данных).
- `tests/test_extra_cover_styles_api.py` — `test_select_per_chat` обновлён под реальный контракт
  (форма патча + `pg=` + сохранение чужого override); НОВЫЙ `test_select_clear_removes_override`.
- `tests/test_cover_styles_contract_asap32.py` — FakeDB/FakeConn расширены chat_profiles SQL
  (SELECT/UPDATE chat_params, chat_lore_history, pg_notify, advisory); helper `_put_chat_profile`;
  НОВЫЙ класс `TestSelectPersistsViaChatParams` (4 теста): сквозной select → real chat_params →
  fake pool БЕЗ monkeypatch chat_params (§120-урок); обновлён stub-сигнатура в
  `test_non_admin_can_list_and_select` (`**kw` — pg= теперь передаётся).

## Верификация

- RED-on-pre-fix: `git stash push -- web/api/cover_styles.py` →
  `TestSelectPersistsViaChatParams`: **3 failed** (503 на pre-fix) / 1 passed (404 unknown style);
  stash pop — фикс возвращён. Требование §120 «регрессия падает на pre-fix» выполнено.
- Целевые файлы: `pytest tests/test_cover_styles_contract_asap32.py tests/test_extra_cover_styles_api.py -q`
  → **37 passed**.
- Полный pytest: `python -m pytest -q` → **10437 passed / 2 failed** за 309.9s. Оба падения —
  якорные `test_forbidden_paths_out_of_diff` (tool_coordinator_round1026, unified_image_request_round1026)
  — воспроизведены и ДО моих правок тем же stash-приёмом (2 failed на чистом базисе); это
  документированный локальный базис («полный pytest 10432/2», коммит 1a25d48; в официальном
  гейте якоря deselect-ятся). Δ: 10432+5 новых тестов = 10437; новых падений 0.
- JS: `node --check web/app.js` → OK (файл не менялся).
- F8: `python tools/gen_param_registry_round1025.py --check` → `CHECK OK: реестр 488 == REGISTRY…`,
  exit 0 (каталог не расширялся).

## Acceptance-покрытие

- Выбор seeded-стиля (medved_press) сохраняется в PG в форме `overrides[key]`, читающий путь
  (`_resolve_from_root`, каст по каталогу) резолвит выбор — regression, RED на pre-fix.
- Прочие per-chat overrides чата не затираются (guard от namespace-replace).
- Снятие выбора (пусто) удаляет override → работает глобальный hot/дефолт (DC-5).
- Неизвестный style_id → 404 до записи.
- Non-admin может выбирать (access); seeded-профиль мутирует только admin (существующие §135-тесты зелёные).

## Не проверено (за пределами локальной среды)

- Живой authenticated выбор стиля в мини-аппе на staging/prod (нужен real Telegram init-data +
  real PG) — за Reviewer/DevOps при деплое 2.58.43. Локальный Browser-smoke не проводился:
  UI-код (web/app.js) не менялся, изменение — backend-only реставрация задуманного контракта.
- Поведение при отсутствующем `chat_profiles`-ряде чата → честный 503 (как и остальные
  chat_params-писатели; профиль создаётся lifecycle при входе бота в чат).
