# EXTRA — deployment / migration / rollback (Block K, T-4183…T-4188)

> **Фича:** `extra-cover-style-pipeline` (EXTRA, round1029). **Risk:** R3.
> **Baseline:** prod `2.58.39` (bump c `2.58.38`). **Деплой — @DevOps** (сам
> деплой в этом документе не выполняется). **Откат §95.**

---

## 1. Версия и артефакты

- **bump:** `APP_VERSION` `2.58.38 → 2.58.39` (`config/settings.py`).
- **Δ DDL SQLite = 0** — `PRAGMA user_version` остаётся **19** (никаких новых
  шагов `mca-14`); `mca-04b` сохраняет бронь `v20` (ADR-1027-9 D13 не правится).
- **Δ PG-DDL ≠ 0** — 5 аддитивных таблиц + индексы через
  `services/pg_db.py::DDL_STATEMENTS` (идемпотентно, прецедент A5):
  `cover_style_profiles`, `cover_style_references`, `cover_style_assets`,
  `cover_style_issue_assignments`, `cover_style_provenance`.
- **Δ каталога = +4** ParamSpec (3 connection + 1 per-chat selection);
  F8-артефакты не менялись по счётчикам (**488 / 427 / 463 / 105 / 103 / 21**);
  `tools/gen_param_registry_round1025.py --check` — OK.
- **Файлы ассетов (не в git):** `var/cover_style_assets/` (env
  `COVER_STYLE_ASSETS_DIR`); seed-файлы `extra_images/*` **копируются**
  (originals не мутируются, R18).

## 2. Migration safety (§94)

1. **PG-инициализация идемпотентна:** `CREATE TABLE IF NOT EXISTS` при старте;
   повторный запуск — no-op; существующие данные/таблицы не затронуты.
2. **Существующие Summary не ломаются:** config без выбора стиля
   (`prompts.summary_cover_style_id` пусто/отсутствует) → автоматически
   `Без дополнительного стиля` → ровно текущий base-путь. Старое поведение
   default-compatible.
3. **Seed идемпотентен (§59):** профиль `Графический роман Медведь Press`
   создаётся один раз; повторный старт — no-op; ручной стиль не перезатирается.
   Ассеты импортируются `ON CONFLICT DO NOTHING` (дедуп по `sha256+scope`).
4. **PG недоступен:** Style-функции деградируют fail-soft (base cover +
   публикация продолжают работать; §1). Kill-switch и degraded-режим безопасны.

**Проверка (T-4183, @DevOps):** прогнать идемпотентный PG-DDL init на
копии/эталоне; повторный старт — no-op; `PRAGMA user_version` = 19;
`extra_images` импортированы один раз (повтор — 0 новых строк).

## 3. Rollback (§95)

| Уровень | Действие | Результат |
|---|---|---|
| **Hot (soft)** | `COVER_STYLES_ENABLED=false` (env-only) | Style-стадия полностью пропущена; base cover + публикация живы; Style UI — disabled. |
| **Hot (контур)** | `COVER_RICH_DEGRADED_ENABLED=false` | Откат изменения публикационного контура T-4145 → cover-failure снова plain (baseline parity §90/§95). |
| **Cold** | `git revert` релизного коммита | PG-таблицы аддитивны (SQLite Δ=0); **откат base-cover функциональности не требуется**. |

- Миграционного откатa base cover не существует и не требуется (Δ SQLite = 0).
- PG-таблицы можно оставить (аддитивны) либо удалить вручную — данные не влияют
  на base-путь.

**Drill (T-4184, @DevOps):** `COVER_STYLES_ENABLED=false` → реальный Summary
публикуется как раньше (base+Rich), Style UI disabled; `git revert` cold-tested.

### Env-only переключатели EXTRA (Δ каталога = 0)

| Переменная | Default | Назначение |
|---|---|---|
| `COVER_STYLES_ENABLED` | ON | Master kill-switch optional Style-слоя. |
| `COVER_RICH_DEGRADED_ENABLED` | ON | Degraded RichMessage без обложки (§51). |
| `COVER_STYLE_EDIT_TIMEOUT_SECONDS` | 240 | Окно одной попытки edit (кламп [30, 900]). |
| `COVER_STYLE_EDIT_MAX_ATTEMPTS` | 1 | Попытки edit (кламп [1, 3]; повтор дорогой). |
| `COVER_STYLE_EDIT_RETRY_BACKOFF_SECONDS` | 5 | Пауза между попытками. |
| `COVER_STYLE_HEARTBEAT_SECONDS` | 30 | Период heartbeat-лога долгой стадии. |
| `COVER_STYLE_METRICS_ENABLED` | ON | Process-local latency/cost метрики. |
| `COVER_STYLE_CAPABILITY_TTL_SECONDS` | 900 | TTL кэша capability. |
| `COVER_STYLE_CAPABILITY_OVERRIDES` | "" | JSON-override capability (аварийный escape hatch). |
| `COVER_STYLE_ASSETS_DIR` | `var/cover_style_assets` | Managed-каталог файлов ассетов. |
| `COVER_STYLE_ASYNC_SUBMIT_URL` / `_STATUS_URL` | "" | Async submit/poll (capability-gated; без contract не включается). |

## 4. Production acceptance checklist (§100, T-4186 — @DevOps)

- [ ] **No Style:** реальный Summary без стиля — base cover сгенерирована,
      RichMessage опубликован, поведение не деградировало (§90).
- [ ] **Medved Press:** реальный Summary со стилем — base cover → style
      processing → reference `medved_press.png` → issue number → styled cover →
      Rich publication.
- [ ] **Style failure:** смоделировать отказ style-стадии (без разрушительного
      вмешательства) → опубликована **base cover**, Summary успешен.
- [ ] **Base failure:** base generation не удалась → **RichMessage без
      изображения** (degraded `media=[]`), статья сохранена.
- [ ] **Rich failure:** rich-отправка не удалась → обычный `sendMessage`,
      тело статьи сохранено.
- [ ] **UI:** seeded style; thumbnails; references; create custom; duplicate;
      edit; counter; preview (Test Style); connection redirect; mobile.
- [ ] **Logs:** для одной успешной и одной degraded публикации понятна точная
      упавшая стадия (`COVER_*`, fallback ladder §96).
- [ ] **Health:** health 200, `database is locked`=0, `version=2.58.39`.

## 5. Продуктовые предусловия (§101)

- **DC-4:** реальный Style Edit требует **edit-capable provider** в Connections
  (текущий код-дефолт Pollinations/flux edit не умеет → §38-сообщение, при этом
  **base публикуется корректно**). Не блокер деплоя.
- **DC-2 (D8):** стартовое значение seeded counter — **owner-input required**;
  до решения владельца действует обратимый дефолт `0` (`SEEDED_COUNTER_START`).
