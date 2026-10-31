# EVOL — план релиза (подготовка, без выката)

Подготовлено: 31.10.2026, 19:22–19:40 +12:00 (07:22–07:40 UTC). Статус: **ПОДГОТОВКА, ДЕПЛОЙ НЕ ВЫПОЛНЕН**.
Владелец роли: DevOps. Проверки только HTTP + локальный Git, SSH не использовался.

## 1. Кандидат и точка опоры

| Параметр | Значение |
|---|---|
| Кандидат (ветка) | `evol/impl`, worktree `…\workspaceData\worktrees\c742e4de9e92c489\evol-71536a366a11-c63f6f44` |
| HEAD | `1e0ad895f959ecee60d39483b6c0fa9c4540969a` |
| База линии | `4aa91baf` (W0-планирование EVOL, 2.58.141) |
| Продакшн-база | `5346ee76` (bump 2.58.140 → 2.58.141) — **предок** HEAD, FF возможен |
| Линия деплоя | `release/p0-2026-10-26` (origin tip `1f4fe81a`, содержит `5346ee76`) |
| `origin/master` | `24ca634b` (2.58.128) — **устаревшая линия, НЕ деплой-таргет** |
| `master` (локально) | `3193b657` (2.58.111) — предок `evol/impl`, но не деплой-линия |
| `1f4fe81a` в `evol/impl` | **нет** (только docs-запись деплоя 2.58.141, 1 файл, +119) |
| APP_VERSION в HEAD | `2.58.141` → требуется `2.58.142` |

Линия `evol/impl` линейная (58 коммитов поверх `4aa91baf`), merge-коммитов внутри нет.

## 2. Содержимое релиза

`git log --oneline 4aa91baf..HEAD` = **58 коммитов**. Диф: **376 файлов, +89 562 / −19 175**.
Прикладной код (`services/ handlers/ web/ config/ bot.py`) = **61 файл, +29 927 / −4 817**.

Кластеры:

| Кластер | Коммиты (выборка) | Объём |
|---|---|---|
| W1 надёжность бэкенда | `0e853f7f` заблудший `_LAST_EMBED` (EVOL-010), `dc1fdba6` reason_code+WARN-dedup (011/013), `e7443fad` TextQuote (015), `28d55bd1` вывод Smart Cache (031) | services/* |
| Prompt-версионирование | `44437903` release policy + `011fe8ff` схема v39 + `c7851980` review-fix (012/016), `be5ad652` история версий UI (017), `95b8d275` контракт (018) | +1891 `prompt_release_policy.py`, перезапись `prompt_registry.py` (6498 строк диффа) |
| Виджеты/диагностика/мемы | `3d52e487` (007–009), `9eeb3532` (014 backend), `4fcbf684` (001–005, 019–021), `98d16b94`, `33a14034` (022/032), `a02aca0c` | `memory_diagnostics.py` +970, `meme_initiative.py` +1403, `episode/experience_diagnostics.py` |
| UI-обвязка волны 4 | `18baa36b`, `d31b8831`, `fc7d0f57`, `f7a906e2` (пины) | `web/app.js` +3870, `index.html` +3285, `app.css` +1288, `routes.py` +1031 |
| Addendum W5 | `0d36b235` SOCIAL-FRAME, `9dc6fba9`+`aeb42517`+`14b67272`+`fcdc69a8` VIDEO-INTENT, `d036707a`+`3f62150f` FACTCHECK-CRITICAL, `3a0f89d2` GLASS-SEAM | `social_turn_frame.py` +392, `video_intent.py` +733 |
| ASAP-FC-ADMISSION-01 | `432c7593` + `d561d68a` | `factcheck_suitability.py` +224 |
| ASAP-FC-EVIDENCE-STYLE-02 | `303e18e8`, `2033a2c0`, `54f44f05` | `factcheck_service.py` +585, `search_aggregator.py` +280 |
| ASAP-VISION-SYNC-01 (P0 corrective) | `390cacaf`, `b6403881`, `ca15a2f6`, `e9cbd050`, `7131897b`, `8d68960d`, `a4be717c` | `media_readiness.py` **+2177**, `mca_vision.py` +1523, `summary_memory.py` +659 |
| UI-волны 023/024/025/026–030 | `cf628f97`, `0318f2ed`, `0316d62b`, `d7eef0f9`, `1e0ad895` | `web/*` (крупнейший UI-блок) |
| Тесты/доки/пины | 143 файла тестов, 156 `plans/**`, `AGENTS.md` (правило media), `407e01fa` медиа-ассеты | — |

## 3. Предпосылки и найденные зазоры

1. **APP_VERSION**: `config/settings.py:3440` = `2.58.141`. Строка версии запинована в **31 файле**: `settings.py`, `README.md`, `plans/docs/param-registry-round1025.meta.md`, 25 py-тестов (`2.58.141`) и 4 js-тестов с экранированным пином (`2\.58\.141`). Прошлый bump `5346ee76` менял 31 файл / 33 строки — тот же набор.
2. **Рабочее дерево грязное**: 17 изменённых PNG в `plans/features/evol/audit/evidence/` (перегенерированы 31.10 ~16:21, только бинарные размеры 94–248 KB). Прикладного кода в незакоммиченном нет. Нужно решение: закоммитить как обновление доказательств либо отбросить (артефакты воспроизводимы) — **до сборки кандидата**.
3. **Медиа**: 7 новых файлов (`goodmorning_07..12.jpg` 19,9–153,4 KB, `slavic_testo.jpg` 211,2 KB), всего в `media/` 65 файлов / 96,4 MB. `media/srv_cookies.txt` в worktree **отсутствует** и покрыт `.gitignore:12` (`*cookies*.txt`); в отслеживаемых файлах `media/**` секретов/куки нет. Правило `AGENTS.md` (owner, 30.10): медиа выезжает вместе с деплоем → сверить наличие файлов на сервере после `git pull`.
4. **Путь деплоя** (подтверждён по `AGENTS.md` и `deploy_commands.txt`): `ssh root@192.255.209.205`, каталог `/var/www/admin_bot`, штатно `git pull --ff-only` + `systemctl restart admin_bot`. Remote: `https://github.com/Henry-Case-dev/adminbot.git`. `deploy_commands.txt` в `.gitignore` (строка 20) и содержит **пароль в открытом виде** — не коммитить, не печатать, не копировать в отчёты.
5. **fail2ban**: баны по SSH, HTTP не задевает. Работать одним recon-коннектом и одним основным прогоном; порт закрыт → пауза ≥22 мин, максимум один автоповтор.
6. **Схема данных (аддитивно)**: `services/database.py` добавляет шаги **v38** (`quote_metadata`) и **v39** (`prompt_revision_journal`) — оба аддитивные, SQLite no-op по данным + `PRAGMA user_version`. **v40 не зарегистрирован**: журнал квот мемов (`meme_initiative.py`, `SqliteQuotaLedger`) схему в горячем пути не создаёт (`apply_schema` — только тест/будущий шаг), поэтому на проде квота мемов честно уйдёт в `schema_absent`. Последствие: **EVOL-014 backend выкатится в честно-выключенном виде**; нужна отдельная задача «шаг v40». Деградация объявлена контрактом фичи, откат кода при более новой схеме безопасен.
7. **ENV**: новых обязательных ключей нет. Добавлены опциональные с заводскими дефолтами: `VISION_MAX_OUTPUT_TOKENS`, `MCA_VISION_READINESS_WAIT_SECONDS`, `MCA_VISION_ASSOCIATION_WINDOW_SECONDS`, `MCA_VISION_PENDING_INTENT_TTL_SECONDS`, `MCA_VISION_JOB_LEASE/QUEUE_WAIT/LIFETIME/MAX_RECOVERIES/BACKOFF_*`. `SMART_CACHE_ENABLED` и `SMART_CACHE_TTL_SECONDS` больше не читаются (поля оставлены ради старых `.env`) — правка `.env` на сервере не требуется.
8. **Покрытие ревью (главный блокер)** — см. §7.

## 4. Путь интеграции (рекомендуемый)

`origin/master` устарел, `master` = 2.58.111 → интегрировать туда нельзя. Использовать установленный формат версионной релизной ветки (`origin/release/2.58.x`), ответвлённой от продакшн-базы:

```bash
# 0) чистое дерево на кандидате (сначала §3.2)
git -C <worktree> status --porcelain        # ожидается пусто

# 1) релизная ветка строго от продакшн-базы, FF на кандидата
git -C <worktree> checkout -B release/2.58.142 evol/impl
git -C <worktree> merge-base --is-ancestor 5346ee76 HEAD && echo "FF-база OK"

# 2) перенести docs-запись деплоя 2.58.141 (необязательно, docs-only)
git -C <worktree> cherry-pick 1f4fe81a    # конфликт в plans/ → пропустить и зафиксировать в отчёте

# 3) bump версии (§5), 4) проверки (§6), 5) push
git -C <worktree> push -u origin release/2.58.142
```

Запрещено: merge в `master`/`pull` старой линии, `rebase`/`reset` линии `evol/impl` (сменит хеши отревьюенного кандидата), `push --force`.

Деплой (один SSH-прогон, после «go»):

```bash
ssh root@192.255.209.205
cd /var/www/admin_bot
git fetch --prune origin
git status -sb && git rev-parse HEAD          # зафиксировать прод-HEAD до выката
git checkout release/2.58.142 && git pull --ff-only
git rev-parse HEAD                            # сверить с кандидатом
systemctl restart admin_bot
```

Откат: `git checkout release/p0-2026-10-26` (== `1f4fe81a`, продакшн 2.58.141) + `systemctl restart admin_bot`. Схема аддитивна (v38/v39), откат кода совместим; v40 не применяется.

## 5. Шаги bump 2.58.141 → 2.58.142

1. `config/settings.py` — `APP_VERSION = "2.58.142"` (+ короткая запись в комментарии о содержании релиза).
2. `README.md` — строка версии.
3. `plans/docs/param-registry-round1025.meta.md` — мета-версия (2 строки).
4. 25 py-тестов с пин-строкой версии: `tests/test_webapp_*.py` (f6/f7/f9/f11/hotfix6–10/design_tokens/round1026_polygon), `test_summary_*` (5 файлов), `test_decision_making_round1026`, `test_image_context_memory_round1026`, `test_mca17c_invariants_round1047`, `test_round1025_f8_registry`, `test_scope_selector_round1025`, `test_telegram_reactions_round1026`, `test_tool_coordinator_round1026`, `test_unified_image_request_round1026`, `test_evol010_embedding_defects`.
5. 4 js-теста с экранированным пином `2\.58\.141`: `tests/js/round1025_hotfix7/8/9/10_*.js` (искать `2\\.58\\.141`, простая подстрока `2.58.141` их не находит).
6. Комментарии-упоминания версии в `services/embedding_control_plane.py` (строка ~1426, историческая) не трогать.
7. Отдельный коммит `chore(release-258142): bump 2.58.141 -> 2.58.142 (...)` с фиксацией: `compileall` rc, проверка реестра, дельта пинов, `deltaDDL`.

## 6. Проверки до выката (на кандидате)

Уже выполнено сейчас (факт, HEAD `1e0ad895`):
- `py -m compileall -q services handlers web config bot.py` → rc=0 (файла `database.py` в корне нет, модуль — `services/database.py`).
- `pytest tests/test_webapp_evol_w9_responsive.py tests/test_webapp_evol_w10_sections.py tests/test_webapp_evol_w7_nav.py -q` → **85 passed** (31 с).
- `pytest tests/test_evol_vision_sync_core.py -q` → **35 passed** (8 с).
- HTTP-пробы прода (см. §8): живо, 2.58.141.

До выката повторить/добавить на финальном коммите (после bump):
- `py -m compileall -q services handlers web config bot.py` → rc=0;
- проверка реестра промптов (`tests/test_round1025_f8_registry.py`, `registry --check`, ожидание 586 == REGISTRY — уточнить актуальное число после EVOL-012/016);
- дельта пинов каталога = 0 относительно базы (известные 18 устаревших пинов — предсуществующие на деплой-линии);
- фокусные наборы EVOL: `tests/test_evol*.py`, `tests/test_webapp_evol_w*.py`, `tests/js/*evol*.js`, `tools/ui_evol_w7_nav_e2e.py`, `tools/ui_evol_w9_responsive_e2e.py`, `tools/ui_evol_w10_sections_e2e.py`;
- статический `deltaDDL`: список DDL-шагов базы == v39 (v40 отсутствует — ожидаемо);
- медиа-чек «до»: 7 новых файлов присутствуют в коммите (`git show --stat`).

## 7. Объём: что считается выкатываемым

**Отревьюено и технических вопросов нет (24 требования + 1 corrective):**
EVOL-001…022, EVOL-031, EVOL-032 — в `requirements-map.json` `review_verdict: APPROVED` с привязкой к кандидатам (`98d16b94`, `a02aca0c`, `0e853f7f`, `dc1fdba6`, `c7851980`, `e7443fad`, `be5ad652`, `4fcbf684`, `33a14034`, `7492d325`); ASAP-FC-ADMISSION-01 — `APPROVED_BEHAVIOR` (`432c7593`).

**Без вердикта ревью (нельзя объявлять выкаченным как принятое):**

| Волна | Факт в ветке | Состояние |
|---|---|---|
| EVOL-023/024 (навигация/топбар) | `cf628f97`, review-fix `0318f2ed` | записи ACCEPT не найдено |
| EVOL-025 (адаптив) | `0316d62b`, review-fix `1e0ad895` | **ожидает финального вердикта (review-fix)** |
| EVOL-026…030 (разделы UI) | `d7eef0f9`, review-fix `1e0ad895` | **ожидает финального вердикта (review-fix)** |
| EVOL-SOCIAL-FRAME / VIDEO-INTENT / FACTCHECK-CRITICAL | `0d36b235`, `9dc6fba9…`, `d036707a…` | `BUILDING` в карте |
| EVOL-GLASS-SEAM | `3a0f89d2` | `PENDING` |
| ASAP-FC-EVIDENCE-STYLE-02 | `303e18e8`+2 fix | строк в карте нет |
| ASAP-VISION-SYNC-01 (P0) | 7 коммитов, последний review-fix3 | 93 required-строки `PENDING` |

**Не в этом релизе:** EVOL-033 (не начато), EVOL-034…045 (не начато), EVOL-DoD, EVOL-SRC-READER, EVOL-COG-MAP (не начато).

**Важно:** физически «вырезать» непринятые волны нельзя — линия линейная, а нужные review-фиксы принятых слайсов лежат **позже** непринятых коммитов (например `d31b8831` правит UI 021, `1e0ad895` — адаптив/разделы). Поэтому корректный релиз = **одна финальная ревизия HEAD после вердикта Reviewer по всему дельту**. Альтернатива «собрать кандидата из `7680aeef` + cherry-pick» создаёт новую непроверенную комбинацию и требует полного ре-ревью — рискованнее, чем дождаться вердикта.

## 8. Продакшн до выката (HTTP)

2026-10-31 19:22:27 +12:00 (07:22:27 UTC), `https://admin-bot.duckdns.org`:
`/healthz` → 200 `{"status":"ok","version":"2.58.141"}`; `/api/health` → 200 `{"status":"ok"}`; `/web/` → 200, 930 269 байт `text/html; charset=utf-8`.

## 9. После выката (обязательный минимум)

1. `git -C /var/www/admin_bot rev-parse HEAD` == выкаченный кандидат; `/healthz` = `2.58.142` (сверить независимо от локального Git).
2. `/api/health` 200, `/web/` 200 (сверить размер/хеш ассетов с локальными), `systemctl show -p NRestarts` = 0.
3. `journalctl -u admin_bot --since <restart>`: без `Traceback`/`ERROR` (отделить известные предсуществующие: wikipedia-403 anticliche, DDG taxonomy).
4. Миграции: `PRAGMA user_version` = 39 (локальная SQLite), наличие `prompt_revision_journal`, шаг v38/v39 в логах; v40 отсутствует — ожидаемо.
5. Медиа-чек «после»: 7 файлов на сервере, размеры совпадают (96,4 MB каталог целиком).
6. Живые смоуки по изменённому критическому пути: фактчек-запрос, vision-фото путь (через API/админ-UI, без отправки проб в реальные Telegram-чаты владельца без отдельного разрешения), открытие `/web/` в Playwright 1280×900 и 390×844 + визуальный смоук Browser Use.
7. Требования карты: `requirements_gate.py check --stage release` на выкаченном кандидате — только после заполнения `candidate_commit`/`deployed_commit` и доказательств (`live_required`: EVOL-010, EVOL-031 — `postdeploy`).

## 10. Блокеры и статус

| # | Что | Кто снимает |
|---|---|---|
| B1 | Вердикт Reviewer по полному дельту HEAD (023–030, addendum W5, FC-EVIDENCE-STYLE-02, VISION-SYNC-01) | Reviewer |
| B2 | Диспозиция 17 изменённых PNG-доказательств (коммит или отброс с причиной) | Reviewer/Builder |
| B3 | Bump `2.58.142` + коммит release | DevOps (после B1) |
| B4 | `requirements-map.json`: `candidate_commit` = финальный, `deployed_commit` пуст; `workflow_state.md` относится к предыдущей задаче (не EVOL) | PM |
| R1 | Шаг миграции **v40** (журнал квот мемов) не интегрирован → EVOL-014 на проде честно выключен | Builder (не блокирует выкат) |
| R2 | `deploy_commands.txt` хранит пароль открытым текстом (файл в `.gitignore`) | владелец/DevOps, не блокирует |

Итог: технически кандидат собран и локально зелёный; выкат **заблокирован только отсутствием финального вердикта Reviewer** и диспозицией грязного дерева.
