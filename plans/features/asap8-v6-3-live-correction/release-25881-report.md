# RELEASE-GLASS-ISO — изолированный релиз 2.58.81 (glass + v6.3-tails + SSRF) на прод: отчёт

Дата: 2026-10-17. Лейн: RELEASE-GLASS-ISO (release engineer). Владелец одобрил план изоляции.

## Ответ на вопрос владельца: стекло изолируется безопасно — ДА

1. Все три cherry-pick'а применились **чисто, без конфликтов**: `9e63b3cf`, `02f8ab91`, `473f2cc1`.
2. **Зависимости от W1 нет**: `git diff 31c16555..release/glass-2.58.81` по
   `services/prompt_registry.py|prompt_factory.py|prompt_style_blocks.py|prompt_migrations.py|param_catalog.py` — **пуст**
   (`w1-diff-empty.txt`, 0 байт); payload (web/, tests/js, tests/glass-teststand, requirements.txt,
   services/web_content_extractor.py, новые тесты) **побайтово == master `473f2cc1`** (`glass-identical-to-master.txt`, 0 байт
   на пре-bump tip `2aa512e6`); tip ветки vs master отличается ровно W1-файлами (35) + версионными файлами bump (31) − пересечение
   (`isolation-vs-master.txt`, 65 файлов, ничего иного).
3. Единственная оговорка (не блокер изоляции, см. «Находка»): committed `design_tokens`-тест RED — **это состояние самого master**,
   не следствие разделения.

## Deploy binding

| Поле | Значение |
|---|---|
| DEPLOY_SOURCE | локальный репо `C:\Code\Python\adminbot`, ветка `release/glass-2.58.81`; релизный коммит `6d4b9a7d645dcd0e7bd6c63b1e3ce2d367b58221` (`6d4b9a7d`) |
| База ветки | `31c16555` (2.58.80 = прод) + `ea933769` (SSRF) + `ae7fd6a4` (v6.3 tails) + `2aa512e6` (glass) + `6d4b9a7d` (bump) |
| Push | `git push -u origin release/glass-2.58.81` (обычный, без force); origin = `6d4b9a7d` |
| Сервер | `git fetch origin release/glass-2.58.81` + `git checkout -B release/glass-2.58.81 origin/release/glass-2.58.81`; HEAD сервера = `6d4b9a7d` (tracking origin) |
| Предыдущий прод (rollback) | `31c165556dbe8c289606bd6bee1af49bb72d5794` (2.58.80) |
| MUTABLE_WORKTREE_REQUIRED | **no** — деплой из immutable закоммиченного дерева; незакоммиченная работа соседних лейнов (SOUL-1 WIP) в релиз не попала |
| DDL / миграции | ΔDDL = 0 (в дельте нет migrations/*, database.py, pg_db.py, schema registry) |
| Версии | 2.58.80 → **2.58.81** (31 файл, 33 ins/33 del: settings + README + F8-meta + 24 py + 4 JS-пина; F8-meta HEAD = `2aa512e6`) |

## Branch log (ровно 3 cherry-pick + bump)

```
6d4b9a7d chore(release-glass-iso): bump 2.58.81 — изолированный релиз glass + v6.3-tails + SSRF ...
2aa512e6 feat(glass): Tier A refraction on ALL MiniApp glass surfaces + owner-ordered strengthening...
ae7fd6a4 fix(v6.3 tails): remove the anonymously served glass test stand from production static + ...
ea933769 fix(security): safe-fetch guard no longer depends on an optional package (SOUL-13/v6.3)...
```
`git diff --stat 31c16555..release/glass-2.58.81 -- services/prompt_registry.py services/prompt_factory.py services/prompt_style_blocks.py services/prompt_migrations.py services/param_catalog.py` → **пусто**.

## Фокусные проверки ветки (в отдельном worktree; main worktree не тронут)

| Проверка | Результат |
|---|---|
| `node tests/js/glass_probe_test.js` | `JS-UNIT-OK glass-probe`, exit 0 |
| `node tests/js/round1025_design_tokens_test.js` | **RED** (см. Находку) — `TypeError: this._lgGlassSelector is not a function`; с WIP-фиксом (blob `26fc9ef7`) → `JS-UNIT-OK` |
| pytest `test_webapp_teststand_guard` + `round107` + `round1010` + `test_soul13_ssrf_guard_order` | **47 passed** |
| pytest tails-touched (`test_mca16_experience_block_d_round1039`, `test_tool_coordinator_round1026`, `test_unified_image_request_round1026`) | **103 passed** |
| `tools/ui_asap8_w2_shell_e2e.py` | `W2-SHELL-E2E-OK` (failed_checks {}, console_errors []) |
| `tools/ui_asap8_w2_fullscreen_e2e.py` | **7/7 PASS** |
| После bump: `node hotfix7-10` | **4/4 OK**; pytest pins (`f8_registry`+`design_tokens`+`f11`+`scope`) **123 passed**; `gen_param_registry_round1025.py --check` → `CHECK OK: 572 == REGISTRY` |

## Деплой и live-верификация (всё с сервера; детали — `ev_verification_summary.md`)

- Сервис: `active/running`, MainPID=2854731, NRestarts=0, ExecMainStatus=0.
- `healthz` (loopback и 443): `{"status":"ok","version":"2.58.81"}`.
- Файлы сервера 5/5 побайтово == релизному коммиту (app.css/app.js/index.html/param_catalog.py/settings.py).
- Отдача: `/web/` 200 (sha == ожидаемым substituted-байтам; `2.58.81`×14, `2.58.80`×0); `/web/app.js` 200 sha == raw;
  `/web/static/app.css` 200 sha == raw; `/static/app.css` 200 sha == substituted; **линза усилена: `scale="32"`×1, `lg-lens-map`×1**.
- Тест-стенд: 6 путей + HEAD + `?v=` → **404**; живые ассеты → 200.
- W1 отсутствует на сервере (`prompt_registry.py`/`prompt_factory.py` нет); runtime-проба: version=2.58.81, каталог-ключ есть,
  `lxml_html_clean=ok`, `trafilatura=ok`.
- Журнал после рестарта: 292 строки, `ERROR=0 CRITICAL=0 Traceback=0 database-locked=0`.

## Rollback (не потребовался; готовность)

```bash
ssh nik@198.46.175.136
cd /var/www/admin_bot
git diff > /tmp/pre_rollback_local.patch     # страховка для tracked-правок, если появятся
git checkout master                           # локальный master = 31c16555 (2.58.80), ancestor → сеть не нужна
sudo systemctl restart admin_bot
curl -s http://127.0.0.1:8000/healthz         # ожидаем {"status":"ok","version":"2.58.80"}
```
Резервный вариант, если master сдвинется: `git checkout --detach 31c165556dbe8c289606bd6bee1af49bb72d5794`.
Откат DDL не нужен (DDL=0). Мягкие откаты: CSS/каталог — cold revert (флагов нет).

## Находка (не блокер прод-пути, требует закрытия лейном-владельцем)

**committed `tests/js/round1025_design_tokens_test.js` (blob `58273438`) RED против нового `app.js`** из `473f2cc1`:
мок-фейк не содержит `_lgGlassSelector/_lgDenseSelector/_lgNestedInGlass`. Это **состояние master `473f2cc1`**, не следствие изоляции
(та же версия файла и app.js). Зелёное свидетельство review-tiera было привязано к **незакоммиченному** WIP-blob `26fc9ef7`
(явно указан в `plans/features/soul-1/review-tiera.md`); с ним тест проходит (проверено в worktree). Прод не затронут (рантайм покрыт
e2e: w2_shell OK, w2_fullscreen 7/7). **Требуется: закоммитить фикс теста его лейном** (и, при желании, черри-пикнуть на релизную ветку —
тест-онли).

## Отклонения и наблюдения

1. **SSH-коннекты: 5** (дисциплина AGENTS.md, все логины одиночные и успешные, без ретраев после неудачного auth, разнос ≥40–55 с):
   (a) recon; (b) основной прогон #1 — **мой скрипт** преждевременно сматчил собственный echo-маркер `###CO_DONE###` и закрыл канал,
   успев отправить `git checkout` → прерванный checkout оставил частичные копии; (c) основной прогон #2 — честный abort на конфликте
   untracked-файлов; (d) основной прогон #3 — **ремонт + полный деплой**; (e) финальная верификация. Файлы после (b) восстановлены
   безопасно (см. п.2). Продуктовых воздействий от (b)/(c) не было: сервис не рестартовался до (d).
2. **Ремонт состояния после (b)** (deployment-mechanics, продуктовые файлы не менялись): tracked-правки (6: README, settings, meta,
   3 файла стенда — всё «частичные копии») забэкаплены (`/tmp/deploy25881_tracked_mods.patch`, 476 строк) и восстановлены;
   167 untracked-конфликтов забэкаплены (`/tmp/deploy25881_backup/conflicts.tgz` + `aside/`) и убраны; после checkout **166/167
   байт-идентичны целевому дереву** (остатки прерванного checkout), 1 файл (`plans/features/soul-1/evidence/glass-tiera/_strong_real-analytics-a-nolens-1440.png`)
   отличался (неполная копия) — остался в бэкапе, на диске версия из релиза. Исходные untracked-файлы сервера (13 записей на recon)
   не пострадали; tracked-правок на сервере после ремонта 0.
3. **requirements_gate `--stage release` → FAIL (exit 1)** (`gate-release-check.txt`): карта привязана к `31c16555`, наш кандидат
   `6d4b9a7d`; карта **не редактировалась** (DO_NOT_TOUCH; «зеленить» запрещено). Финальный re-capture — за parent/PM.
4. **master пересинхронизирован**: cherry-pick bump-коммита → `2e5aac1a` (31 файл, 33/33; авто-merge `test_round1025_f8_registry.py`
   сохранил и версионную строку, и W1-правки; W1 на master цел), нормальный FF-push `31c16555..2e5aac1a`.
   Локальный ref `master` переведён на `2e5aac1a`; **важно**: из-за перевода ref в main worktree у 31 версионного файла индекс
   разошёлся с HEAD («staged revert»-ловушка для активного соседнего лейна) — устранено точечным `git checkout HEAD -- <31 файл>`
   (версионные файлы снова чистые; **ни один WIP-файл соседнего лейна не тронут**, его staged-набор сохранён).
5. F8-meta `HEAD (short)` = `2aa512e6` (родитель релизного коммита на ветке; upstream-эквивалент — `473f2cc1`). Та же конвенция, что у 2.58.80.
6. Отчёт/evidence **не коммитились** (как и `deploy-25880-report.md` у предыдущего лейна) — по решению parent/PM; при необходимости
   коммитятся отдельным docs-коммитом.
7. Прод-находок при деплое нет. Независимых прод-инцидентов не выявлено.

## Evidence (`plans/features/asap8-v6-3-live-correction/evidence/release-25881/`)

`branch-log.txt`, `w1-diff-empty.txt`, `glass-identical-to-master.txt` (+`-tip`), `isolation-vs-master.txt`, `bump_run.txt`,
`node_glass_probe.txt`, `node_design_tokens.txt`, `node_hotfix7_10_after_bump.txt`, `pytest_guards.txt`, `pytest_tails_touched.txt`,
`pytest_pins_after_bump.txt`, `e2e_shell.txt`, `e2e_fullscreen.txt`, `gen_registry_check.txt`, `ev_recon.txt`,
`ev_deploy_attempt1_aborted.txt`, `ev_deploy_attempt2_aborted.txt`, `ev_deploy_run.txt`, `ev_verify_run.txt`,
`ev_verification_summary.md`, `gate-release-check.txt`.
Скрипты и сырые логи: `OPENCODE_WORKFLOW_SCRATCH/deploy25881/`; worktree ветки: `OPENCODE_WORKFLOW_SCRATCH/glass-release-25881`
(оставлен, detached не нужен — ветка checkout'нута). Серверные бэкапы: `/tmp/deploy25881_backup/`, `/tmp/deploy25881_tracked_mods.patch`,
`/tmp/deploy25881_boot.log`, `/tmp/deploy25881_probe.py`.

## Итог

**2.58.81 @ `6d4b9a7d` задеплоен и подтверждён live-проверками с сервера; W1 не задет; rollback-ready.**
master = `2e5aac1a` (2.58.81) синхронизирован. Coverage-гейт красный из-за несвязанной карты (не правилась) — финальная приёмка за parent.
