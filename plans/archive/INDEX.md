# plans/archive/ — INDEX

Журнал реорганизации plans/ от 2026-10-15 (lane CLEAN-1) + указатель исторических слепков.
Принцип: ничего не удалено безвозвратно — tracked-файлы перемещены `git mv` (история коммитов
сохранена, `git log --follow` работает), untracked — перемещены как есть. Старый плоский архив
фич (≈200 каталогов `plans/archive/<slug>-roundNNNN/`) не тронут; новая волна — в подпапках
`features/` и `reports/`.

## Перемещения 2026-10-15

### Фичи: plans/features/<имя>/ → plans/archive/features/<имя>/ (15 каталогов)

Завершённые эпики; имена сохранены. admin-debug-webview, asap6-current-task-closure (включая
33 untracked evidence-скриншота), asap7-cognitive-direct-pipeline (включая untracked
deploy-w4-evidence.md, sweep-fix-report.md), asap8-reliability-truthfulness, config-read-path-audit,
frontend-admin-bugfixes, mca-10c-game-stub, mca-19-image-understanding, mca-20-temporal-factcheck,
mca-21-guides, mca-asap-summary-hotfix, mca-release (untracked: disk_diagnosis.md D1-disk-diag),
post-deploy-admin-minors, scam-incident-security-followup, user-aliases-admin.

Остались в plans/features/ (намеренно): asap8-v6-remediation (базовые доказательства v6, нужны
v6.3 для B10/reconciliation), asap8-v6-3-live-correction (активная фича).

⚠️ Цитаты старых путей в docstring-ах кода/тестов (например
«plans/features/asap8-reliability-truthfulness/architecture.md» в
tests/test_asap8_f3_style_preservation.py, test_asap8_f8_embeddings.py,
tests/test_asap7_direct_settings.py, plans/features/asap8-v6-remediation/ledger-{c,d}.md,
wc-direct-report.md) — исторические ссылки на контракт; файлы теперь в
plans/archive/features/… (сам код/тесты вне plans/ не менялся).

### Отчёты: plans/reports/<файл> → plans/archive/reports/<файл> (160 файлов)

Вся историческая переписка сканера/ревьюера/манифест-обзоры раундов 10.4–asap5.
ОСТАВЛЕНЫ в plans/reports/ (пinned активными потребителями, перемещение ломало бы их):
- `round1025_f8_config_diff.md` — читается tests/test_round1025_f8_registry.py:423 (+ фиксация в tests/fixtures/round1025/f8_baseline.json);
- `round1025_hotfix6_contrast.md`, `round1025_hotfix7_contrast.md`, `round1025_hotfix8_contrast.md` — assert exists() в tests/test_webapp_hotfix{6,7,8}_round1025.py;
- `round10.16_audit.md`, `round10.16_security_scan.md` — ссылки из README.md (вне write-scope cleanup);
- `round1025_f10_shots/` — gitignored-скриншоты (8 шт.), упомянуты раунд-отчётом 10.25-F10.
`mca20_wth_manifest_review.txt` перемещён вместе с незакоммиченными правками (git mv).

### Корневые файлы plans/

- `round1025-architecture.md` → `plans/archive/round1025-architecture.md` (сентябрьская ступень-карта раунда 10.25; упоминания в ARCHITECTURE.md §40-§46 — исторические, слепок найдётся по этому пути).
- `metrics.md` → `plans/archive/metrics-2026-10-15.md` (append-only журнал эпик-метрик 10.13–ASAP 5); на старом месте — указатель `plans/metrics.md`.
- `MEMORY.md` — полный слепок прежнего содержимого → `plans/archive/MEMORY-full-snapshot-2026-10-15.md`; сам файл переписан в компактный индекс (16 КБ, ≤60 КБ цели).
- `backlog.md` — полный слепок → `plans/archive/backlog-history-2026-10-15.md`; файл переписан: только открытые хвосты/owner-гейты + осознанные остатки v6 (116 КБ из 866 КБ).

### Оставлено без изменений (и почему)

- `plans/ARCHITECTURE.md` (1.9 МБ) — генерируемый архитектурный слепок (последняя актуализация
  03.09.2026, аппендиксы до ~07.10): читается тестом tests/test_avatars_round1017.py:347
  (`open("plans/ARCHITECTURE.md")`) + служит provenance-источником для пинов промптов в
  services/*_prompts.py → перемещение ломало бы тесты. ⚠️ Слепок устарел относительно v6
  (описывает эпоху 2.57.x–2.58.0); живой канон — `plans/docs/canon/architecture.md`.
  Кандидат на будущую реорганизацию вместе с правкой теста (вне write-scope этой lane).
- `plans/verification_cache.json` — кэш evidence-записей верификации, не мусор → оставлен.
- `plans/project.md`, `plans/docs/**` (включая canon/ и mca-round1027-plan.md) — действующие
  справочники/канон, активные ссылки из фич и тестов → оставлены.
- `plans/current_task.md`, `plans/workflow_state.md`, `plans/runtime_task.md` — user/Orchestrator-owned, не тронуты.

## Восстановление

Любой старый путь `plans/features/X/…` → `plans/archive/features/X/…`;
`plans/reports/F` → `plans/archive/reports/F` (кроме списка pinned выше);
`plans/metrics.md` (история) → `plans/archive/metrics-2026-10-15.md`.
Git-история перемещений: коммиты `chore(plans)` от 2026-10-15 (`git log --follow <path>`).
