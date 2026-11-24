# Deploy checklist — 2.58.244 (QRNG UX UI-08..10)

- **Релиз:** 2.58.244, branch `release/qrng-ux-2.58.244`.
- **Production base / rollback:** `10f7c0f5e52cc0eb6efbb88e78e01943d449a3c6`
  = 2.58.243.
- **Content tip:** `eecfdd14842973d9dbea346bd3e3e230af91f5c0`.
- **Bump tip:** `93102d860f447ef261a4842b6721ae0c56f90af1` (2.58.244).
- Финальный tip ветки = этот SHA + evidence/docs-коммит; **деплоить точный
  `git rev-parse HEAD`** ветки, а не «последний master».
- **DDL/миграции/флаги:** **0**. Схема остаётся **v48**. Данные не мигрируют.
- **Зависимости:** `requirements.txt` не менялся — `pip install` не требуется.
- **Исполнитель:** DevOps; Builder deploy/SSH не выполнял.

## 1. Pre-deploy

- [ ] На хосте: `git rev-parse HEAD` = `10f7c0f5e…` (2.58.243), tracked tree
      clean.
- [ ] Сверить целевой SHA с release-веткой; `git diff --name-only
      10f7c0f5e..<target>` — 16 UX-файлов + 32 bump + evidence;
      `migrations/`, `web/api/`, `services/database.py`, `requirements.txt`
      отсутствуют; `config/` — только `APP_VERSION`.
- [ ] Backup БД штатным deploy-путём (keep=2), проверить размер/quick_check;
      свободное место и disk retention; health/логи baseline.
- [ ] Зафиксировать текущие `APP_VERSION`, schema/user_version (48), настройки
      (`random.*`, settings/keys/prompts) и **reserve-счётчики** для
      post-deploy сравнения.

## 2. Deploy

- [ ] `git fetch` + checkout точного target SHA (без merge/rebase на хосте).
- [ ] `python tools/release_manifest.py` на точном SHA → `.deploy/release.json`
      (`version=2.58.244`, `previous_sha=10f7c0f5e…`, `dirty_tracked=false`).
- [ ] `systemctl restart admin_bot`; проверить `NRestarts`, один процесс.

## 3. Post-deploy (агенты; без owner QA)

- [ ] `/healthz`/`/api/health` 200, версия `2.58.244`; identity
      `verified_deployed` (deployed SHA == checkout SHA), schema 48, DDL 0.
- [ ] Настройки/ключи/промпты не сброшены; `APP_VERSION` — единственная
      версия-дельта в конфиге.
- [ ] **Структура главного экрана** (`#/modules/random`, 1440 + 390):
      ровно один select основного источника, один тумблер авторезерва,
      одна последовательность резервов, 3 строки провайдеров; 4 секции
      (Провайдеры/Диагностика/Использования/Дополнительно) присутствуют и
      закрыты; секретов и raw-значений на главном нет.
- [ ] **Один порядок, без дублей:** `используется` встречается один раз,
      effective-провайдер назван один раз, в последовательности нет
      дубликатов и самого primary; на странице нет параллельных блоков
      `saved/factory/effective` и старых подписей
      `A. Диагностика / B. Приоритеты / C. Активность / D. Дополнительно`.
- [ ] **Состояния провайдеров из одного источника:** status
      (`проверено / не проверено / недоступен / выключен / нет данных`) и
      `используется` согласованы между главной строкой, таблицей и
      «Сейчас используется»; причина fallback атрибутирована фактическому
      провайдеру (например, `переключение с IBM Quantum: источник не настроен`).
- [ ] **Reserve-счётчики не изменились:** значения `запас: N` по IBM/ANU/LfDR
      совпадают с pre-deploy снимком; дельта не меняет P5A/P5B, refill и
      batching; скрытого PRNG нет.
- [ ] **Saved-order семантика (key backend change):** при не сохранённом
      primary (`По умолчанию`) и сохранённом порядке select остаётся
      `IBM Quantum`, chip — `сохранено вручную`, effective идёт по
      сохранённому порядку (например, LfDR), note — «Сохранён ваш порядок
      резерва.». Явно сохранённый **пустой** порядок даёт только заводской
      primary без резерва (не заводскую цепочку). Снятое/недействительное
      значение primary (`Требует разрешения`) **не** применяет сохранённый
      порядок и показывает заводскую цепочку.
- [ ] **Диагностика:** для inherited-saved сохранённый, canonical и
      effective порядок различаются честно; `saved != effective` не
      показывает positive «настройки не будут изменены»; absent-mismatch
      называет заводской источник, а не «сохранено».
- [ ] Повторный прогон focused-тестов на deployed SHA:
      `pytest tests/test_qrng_p3_selector.py -q` (**53**),
      QRNG set (**285**), block A..E+JS (**80 passed, 1 pre-existing**).
- [ ] Playwright smoke `tools/ui_qrng_ux0810_e2e.py` (mock-DTO) на deployed
      SHA: **144/144**, 0 console/page errors; Browser Use 1440/390 — 0
      overflow/errors.
- [ ] `journalctl` за окно деплоя: без новых ERROR/Traceback, без секретов;
      disk/backup retention проверены.

## 4. Честные границы (не выдавать за проверенное)

- UI-проверки Builder/Reviewer — mock-DTO, **не live `/api/status`**;
  live-проверка effective-состояния и реальных reserve-значений — только
  post-deploy, по фактическому ответу API.
- Внешние провайдеры (IBM paid jobs, ANU/LfDR квота) релизом не
  активируются и не расходуются; проверка ключей/smoke — только по явному
  действию и за пределами этого деплоя.
- Остаточный backlog: positive chip «Заводской источник выбран» при
  absent-mismatch и note «Доступность источников: 0» — wording/polish,
  BACKLOG, не блокер (r5 review).

## 5. Rollback

- Code-only: checkout/deploy `10f7c0f5e52cc0eb6efbb88e78e01943d449a3c6`
  (2.58.243) + restart; manifest `--effect rollback`.
- DDL/миграций/флагов нет; данные, настройки и схему v48 не откатывать.
- `requirements.txt` не менялся — rollback зависимостей не нужен.

## 6. Известные pre-existing (не блокируют, не правились)

- `tests/test_mca10a_random_source_block_e_round1037.py::test_reason_codes_additive_only`
  — 1 failed на базе и на tip.
- `tests/js/evol_cog_scene_test.js`, `round1025_ia_routing_test.js`,
  `ur_ui_settings_test.js` — 3 failed на базе и на tip (135 pass).
- `tests/test_webapp_round108_ui::TestCacheBustAndEsc108::test_app_version_matches_readme`
  — README содержит `v2.57.0`; воспроизведено на базе (1 failed).
