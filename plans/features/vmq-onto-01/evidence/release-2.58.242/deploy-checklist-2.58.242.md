# Deploy checklist — 2.58.242 (QRNG IBM P5A+P5B)

- **Релиз:** 2.58.242, branch `release/qrng-ibm-p5b-2.58.242`.
- **Production base / rollback:** `3f42cfdd1f7ed26393ba7b793e86efe7b6f73a4c` = 2.58.241.
- **Content+bump tip:** `dfa5118fd294c565e906ff6b78c75bf83427b4fc` (2.58.242).
  Финальный tip ветки = этот SHA + evidence/docs-коммит; **деплоить точный
  `git rev-parse HEAD`**, а не «последний master».
- **DDL/миграции/флаги:** 0. Схема остаётся v48. Данные не мигрируют.
- **Зависимость:** `requirements.txt` + `qiskit-ibm-runtime==0.52.1`; без пакета
  IBM честно отдаёт `dependency_missing`, остальной QRNG работает.
- **Исполнитель:** DevOps; Builder deploy/SSH не выполнял.

## 1. Pre-deploy

- [ ] На хосте: `git rev-parse HEAD` = `3f42cfdd1…` (2.58.241), tracked tree clean.
- [ ] Сверить целевой SHA с release-веткой; `git diff --name-only 3f42cfdd1..<target>`
      не содержит `migrations/`, `services/database.py`, `services/pg_db.py`.
- [ ] Backup БД штатным deploy-путём (keep=2), проверить размер/quick_check; диск
      и свободное место; health/логи baseline.
- [ ] Зафиксировать текущие `APP_VERSION`, schema/user_version, настройки
      (settings/keys/prompts) для post-deploy сравнения.

## 2. Deploy

- [ ] `git fetch` + checkout точного target SHA (без merge/rebase на хосте).
- [ ] `pip install -r requirements.txt` (появился `qiskit-ibm-runtime==0.52.1`);
      при недоступности пакета — не выдавать IBM за рабочий, зафиксировать
      `dependency_missing`.
- [ ] `python tools/release_manifest.py` на точном SHA → `.deploy/release.json`
      (`version=2.58.242`, `previous_sha=3f42cfdd1…`, `dirty_tracked=false`).
- [ ] `systemctl restart admin_bot`; проверить `NRestarts`, один процесс.

## 3. Post-deploy (агенты; без owner QA)

- [ ] `/healthz`/`/api/health` 200, версия `2.58.242`; identity `verified_deployed`
      (deployed SHA == checkout SHA), schema 48, DDL 0.
- [ ] Настройки/ключи/промпты не сброшены; `RANDOM_IBM_*` effective-state виден
      в admin-конфиге.
- [ ] Безопасность: `GET /api/config` и `/api/status.random` не содержат raw
      key/CRN; в DOM/network/логах/422/ошибках только `{configured,last4}`/маска.
- [ ] UI «Модули → Случайность → IBM»: unconfigured → save → stale при правке
      черновика → read-only check; «сохранён» не равен «проверен»; отдельный
      hardware smoke не запускается автоматически.
- [ ] Reserve/fallback counters и переходы IBM→ANU/LfDr; `max_inflight=1`,
      дневные лимиты, throttle refill; скрытого PRNG нет.
- [ ] `journalctl` за окно деплоя: без новых ERROR/Traceback, без секретов;
      disk/backup retention проверены.
- [ ] **Hardware VERIFIED не заявлять:** реальные QPU/IAM/queue/RU/live smoke —
      только после фактического прогона на deployed SHA с реальными key/CRN.

## 4. Owner-only шаг (единственный)

Админка → «Модули» → «Случайность» → IBM: ввести API key + CRN, сохранить,
нажать read-only «Проверить доступ»; опционально — ограниченный smoke
(тратит квоту/QRU). Без этого `QAN-REC-IBM-01..03` остаются **REVIEW**.

## 5. Rollback

- Code-only: checkout/deploy `3f42cfdd1` + restart; manifest `--effect rollback`.
- DDL/миграций/флагов нет; данные и настройки не откатывать. Установленный
  `qiskit-ibm-runtime` без кода 2.58.242 не используется (можно оставить).

## 6. Известные pre-existing (не блокируют, не правились)

- `test_graphrag_rebuild_asap32::test_not_serviceable_warning_coalesced` — `assert 2 == 1`.
- `test_asap5_graphrag_recovery::test_warning_coalesced_not_repeated` — та же причина.
- `test_webapp_round108_ui::TestCacheBustAndEsc108::test_app_version_matches_readme` — README `v2.57.0`.
- `SIMPL-R1-F2` (`<= 1` в `test_p0_embed_admission_msi.py`) — файл не менялся, backlog.
