# Deploy checklist — 2.58.243 (VMQ-MEM RC1–RC7)

- **Релиз:** 2.58.243, branch `release/vmq-rc-2.58.243`.
- **Production base / rollback:** `ff226ca0ae187e8f41fa6cbb3de5317bdcce8f6e`
  = 2.58.242.
- **Content tip:** `95336488d83f192900192cf55ae60f5e2d1dcd02` (merge RC1–RC7).
- **Bump tip:** `fc1d25242d20dc09d443bfcad5aea8a108f2324e` (2.58.243).
- **Test-alignment tip:** `250eb06536f16196e86412a902e1461ffe8871f1`.
- Финальный tip ветки = этот SHA + evidence/docs-коммит; **деплоить точный
  `git rev-parse HEAD`** ветки, а не «последний master».
- **DDL/миграции/флаги:** **0**. Схема остаётся **v48**. Данные не мигрируют.
- **Зависимости:** `requirements.txt` не менялся — `pip install` не требуется.
- **Исполнитель:** DevOps; Builder deploy/SSH не выполнял.

## 1. Pre-deploy

- [ ] На хосте: `git rev-parse HEAD` = `ff226ca0a…` (2.58.242), tracked tree
      clean.
- [ ] Сверить целевой SHA с release-веткой; `git diff --name-only
      ff226ca0a..<target>` — 50 файлов RC + bump/evidence; `migrations/`,
      `config/`, `web/`, `requirements.txt` отсутствуют.
- [ ] Backup БД штатным deploy-путём (keep=2), проверить размер/quick_check;
      свободное место и disk retention; health/логи baseline.
- [ ] Зафиксировать текущие `APP_VERSION`, schema/user_version (48), настройки
      (settings/keys/prompts) для post-deploy сравнения.

## 2. Deploy

- [ ] `git fetch` + checkout точного target SHA (без merge/rebase на хосте).
- [ ] `python tools/release_manifest.py` на точном SHA → `.deploy/release.json`
      (`version=2.58.243`, `previous_sha=ff226ca0a…`, `dirty_tracked=false`).
- [ ] `systemctl restart admin_bot`; проверить `NRestarts`, один процесс.

## 3. Post-deploy (агенты; без owner QA)

- [ ] `/healthz`/`/api/health` 200, версия `2.58.243`; identity
      `verified_deployed` (deployed SHA == checkout SHA), schema 48, DDL 0.
- [ ] Настройки/ключи/промпты не сброшены; `APP_VERSION` — единственная
      версия-дельта в конфиге.
- [ ] **Episode windows:** explicit-year запрос → `DirectChatService.
      _build_old_episodes` даёт target-year anchors в окне, `<Old_Episode>`
      содержит target, order `rank`; пустой/legacy путь не падает.
- [ ] **Ranking positions:** target сообщение explicit-year в top-8/16
      (ожидаемо позиция 2), декабрьские сообщения не вытесняют target;
      p50 rank-запроса в пределах измеренного (~124–130 ms локально).
- [ ] **Year-scoped queries:** explicit-year fact block — только target year,
      out-of-year dropped, «2025:2 + 2026:10» не воспроизводится; current-state
      путь остаётся свежим (2026); «шизах» находит старые 2024-факты.
- [ ] **Reserve/fallback не тронуты:** direct reserve/capacity и QRNG
      P5A/P5B не менялись дельтой; `/api/status.random` — reserve/fallback
      counters и фактические переходы IBM→ANU/LfDr, скрытого PRNG нет.
- [ ] UI: файлов `web/` в дельте 0 — served HTML/CSS/JS эквивалентны
      2.58.242 (кроме версии), визуальная проверка не требуется как новый
      контракт; при сомнении — быстрый Playwright smoke `/web`.
- [ ] 31 focused RC-тест на deployed SHA
      (`tests/test_vmq_mem_rc{1,2,3,4,5a,6a,7}_*.py`).
- [ ] `journalctl` за окно деплоя: без новых ERROR/Traceback, без секретов;
      disk/backup retention проверены.

## 4. Честные границы (не выдавать за проверенное)

- RC5b C-data (read-path/backfill существующих персональных world-фактов) —
  **не реализовано**; меняются только новые строки.
- RC6a E1 (E/Диана 2023–2025) — **отложено**, alias E2 пройден.
- RC7 RFL-7 legacy anchors (14 lore-историй без links) — **отсутствуют**;
  bridge только для новых stories/links.
- Production p95 Writer/Telegram и KNN-семантика RC-путями **не замерялись**;
  живая проверка — после выката по журналу/фактическим запросам.

## 5. Rollback

- Code-only: checkout/deploy `ff226ca0ae187e8f41fa6cbb3de5317bdcce8f6e`
  (2.58.242) + restart; manifest `--effect rollback`.
- DDL/миграций/флагов нет; данные, настройки и схему v48 не откатывать.
- `requirements.txt` не менялся — rollback зависимостей не нужен.

## 6. Известные pre-existing (не блокируют, не правились)

- `tests/test_webapp_round108_ui::TestCacheBustAndEsc108::test_app_version_matches_readme`
  — README содержит `v2.57.0`; воспроизведено на базе `ff226ca0a` (тот же
  failed). `1 failed`.
- `test_graphrag_rebuild_asap32` / `test_asap5_graphrag_recovery` (warning
  coalesce) документированы в 2.58.242; в этом прогоне не запускались, файлы
  дельтой не затронуты.
