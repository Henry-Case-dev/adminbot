# Задачи: budget-overrides-merge-fix-round1024

> **Раунд 10.24 (UPD5-critical)** · Приоритет **P0 / Critical** · Шаг 1 @PM · Тип: backend-багфикс сохранения per-chat настроек
> **ТЗ:** `plans/current_task.md`, **строка 404** (критический баг бюджетов). Файл untracked; секреты не цитировать (R17/R18).
> **Baseline:** HEAD `00eab85`; прод `4314ea4`. Разведка @Memory: `upd4-live-bug-clusters-round1024` + координаты UPD5.
> **Конфликт/AMEND:** **AMEND ADR-1019-8** (write-path per-chat `overrides`) и **AMEND ADR-1012-1** (per_chat / X-Chat-Id save-путь) — ожидаемо **ADR-1024-21**; уточнить разделение namespace `overrides` (значения) ↔ `perm_overrides` (матрица прав).
> **Границы:** F22 `budget-data-repair-round1024` (ремонт уже утерянных данных целевого чата; F20 лишь прекращает потерю); F21 `budget-global-toggle-round1024` (новый master-тумблер).

## Цель
Устранить **корневую причину потери per-chat настроек** (бюджеты-безлимиты целевого чата `-1002661910336` стираются при любом одиночном сохранении в мини-аппе):

`web/api/routes.py:482` берёт `chat_overrides = dict(root.get("perm_overrides") or {})` — это **матрица прав**, а не значения. Далее `:523-529` присваивает namespace `overrides = perm_overrides ∪ {сохранённый ключ}` — то есть **полностью перезаписывает** per-chat значения. Одиночный save (`web/app.js:4454-4461`) уничтожает все прочие per-chat значения (в целевом чате — 8 seed-ключей из `config/chat_settings_seed.json:11-20`, включая `-1`). Затем гейт бюджета (`services/llm_client.py:404-420` → `NoApiKeyForChat('budget')`) уводит бота в фразу-заглушку.

**Правильный образец рядом:** GET `routes.py:372-377` и DELETE `routes.py:729` уже читают `root.get("overrides")` (значения), а `perm_overrides` используют только для матрицы прав.

## Что уже есть (координаты, подтверждены)
- **Баг merge:** `web/api/routes.py:482` (`chat_overrides = perm_overrides`), перезапись `:523-529` (`new_overrides = dict(chat_overrides); new_overrides.update(...)` → `set_chat_params({"overrides": new_overrides})`).
- **Матрица прав (не путать):** `access_srv.effective_matrix(item.key, db_overrides.get(item.key), chat_overrides.get(item.key))` — `:498-503`; это единственное легитимное использование `perm_overrides` в POST.
- **Client save (одиночный):** `web/app.js:4454-4461` — отправляет `items:[{key,value}]` (один ключ) + `updated_at`.
- **Эталоны корректного чтения значений:** GET `routes.py:372-377`; DELETE `routes.py:729`; `services/chat_settings_seed.py:156-179` (читает `root.get("overrides")`, merge `current + patch`).
- **«Самоизлечение» сида:** `bot.py:1049-1051` + `services/chat_settings_seed.py` — при рестарте сид возвращает `overrides`; следующая правка снова стирает (петля).
- **История/аудит:** `chat_lore_history` (`field='chat_params'`) — источник для F22.

## Задачи
- [x] **T-2353** [@Architect] spec.md + ADR (**ожидаемо ADR-1024-21**, **AMEND ADR-1019-8** и **AMEND ADR-1012-1**): контракт merge per-chat значений в `POST /api/config`; явное разделение namespace **`overrides` (значения)** ↔ **`perm_overrides` (матрица прав, только чтение для прав)**; сохранение семантики `per_chat=false` (глобальный путь) и `expected_updated_at`/409; идемпотентность; откат.
- [x] **T-2354** [@Builder] `web/api/routes.py`: база merge значений = `root.get("overrides")` (ключи `:482`+`:523-529`); `perm_overrides` **не** утекает в namespace `overrides` и остаётся только источником для `effective_matrix`/`can_edit_param` (`:498-503`).
- [x] **T-2355** [@Builder] Согласовать read/write: GET `:372-377` и DELETE `:729` (уже `root.get("overrides")`) не меняют поведение; при сохранении значений клиент получает те же `chat_source`/`global_value`; байт-в-байт корректное поведение для нецелевых чатов.
- [x] **T-2356** [@Builder] Регресс-тесты (обязательно все): (a) **два последовательных save** разных ключей — оба сохраняются, ни один не затирается; (b) **seed-overrides выживают** после UI-save (8 ключей `chat_settings_seed.json:11-20`, в т.ч. `-1`); (c) **паритет с DELETE** — после save набор ключей совпадает с ожидаемым; (d) `perm_overrides` **не** попадают в `overrides`, матрица прав применяется как прежде; (e) `updated_at`/409 не сломаны; (f) `per_chat=false` (глобальный путь) не задевает per-chat.
- [x] **T-2357** [@Builder] Идемпотентность и «пустой save»: повтор того же значения — no-op/корректный updated_at; отсутствие ключа-значения не создаёт его; лог `[api] config chat updated` сохраняет ключи/счётчик (R17-safe). Проверить, что `chat_settings_seed` при рестарте больше не «исправляет» искусственно (петля разорвана).
- [ ] **T-2358** [@Reviewer] Ревью: разделение namespace подтверждено (значения ↔ матрица прав); регресс-тесты покрывают сценарий владельца; нет регресса BYOK/sandbox; нет утечек секретов (R17).
- [ ] **T-2359** [@DevOps] Деплой + live-проверка на целевом чате: сохранить значение бюджета в мини-аппе → перезагрузить → значение на месте, прочие per-chat значения не пропали; бот не уходит в заглушку без причины. Отчёт (без секретов).

## Критерии приёмки
- Одиночное сохранение любого per-chat значения **не удаляет** остальные per-chat значения (доказано тестами a–b).
- `perm_overrides` (матрица прав) не попадает в `overrides` и продолжает работать для прав; `overrides` читается/пишется только как значения (паритет с GET/DELETE).
- Восемь seed-ключей целевого чата (в т.ч. `-1` = безлимит) сохраняются после UI-save.
- Полный pytest — 0 failed; `node --check web/app.js` — OK; `git diff --check` чист.

## Риски
- **R1 (Critical):** недостаточный фикс (продолжение затирания) → регресс-тесты (a/b) как контракт.
- **R2 (High):** смешение namespace ломает матрицу прав (`permsoc`/`can_edit_param`) → тест (d) + сохранённое использование `perm_overrides` только в `effective_matrix`.
- **R3 (Medium):** конфликт `web/api/routes.py` с F11 (BYOK `/api/config/keys/own`) и F22 → ступень **F11 → F20 → F22**.
- **R4 (Medium):** `expected_updated_at`/409 регресс на конкурентных save → тест (e).
- **R5 (Low):** секреты в отчётах/логах (R17/R18).

## Зависимости / ступени
- Зависит от: — (чистый багфикс; F22 зависит от F20).
- Ступень общих файлов: `web/api/routes.py` — **F11 → F20 → F22**; `web/app.js` — только при необходимости (web-очередь раунда, согласовать с F3/F5/F6/F11/F4/F10).
- Feature flag: **не требуется** (поведенческий фикс). Откат — `git revert`.
- **Δ DDL = 0, Δ каталога = 0.**
