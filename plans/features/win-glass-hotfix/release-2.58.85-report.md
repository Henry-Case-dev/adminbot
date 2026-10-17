# RELEASE-WG-25885 — изолированный релиз WIN-GLASS-P0 (2.58.85): отчёт

Дата: 2026-10-18 (локально; деплой-сессия 2026-10-17 21:04–21:06 UTC — серверное время).
Лейн: REL-WG (release engineer). Режим: release-ветка + штатный деплой.
Вход: `review-wg.md` R2 Approved (кандидат `0ca661fe`, привязка `f0d4b15f`). PET_PROJECT:
релиз готового и проверенного P0-исправления выполнен штатно; тесты/изоляция/откат сохранены.

## Вердикт (одной строкой)

**Кандидат `0ca661fe` (семантика) задеплоен на прод как 2.58.85: healthz `{"status":"ok","version":"2.58.85"}`
(loopback + 443 + извне), все пост-пробы 200, хэши отданных файлов 5/5 == расчётным,
`/static/glass-refraction.js` 200 (sha `6a09d962d59d`), e2e 37/37 на задеплоенных байтах, в журнале
0 ERROR/CRITICAL/Traceback; SOUL-1 в релизе нет (изоляция доказана: дельта 39 файлов = 8 порт + 31 бамп,
маркеры 0, `fullscreen-policy.js` байт-в-байт `96db06425079`). 7 live-строк (RFL) — за владельцем
(`PENDING_OWNER_E2E`), НЕ VERIFIED; карта не менялась (леджер — отдельно).**

## Deploy binding

| Поле | Значение |
|---|---|
| DEPLOY_SOURCE | локальный репо `C:\Code\Python\adminbot`, worktree `OPENCODE_WORKFLOW_SCRATCH/win-glass-release-25885/wt`, ветка `release/win-glass-2.58.85`, tip **`9552686391dfe69dd7cb08ba7cd800a8a6c5106e`** |
| База ветки | **`0b7a0aca`** (задеплоенный 2.58.84, ветка `release/fs-2.58.84`) |
| Состав | `0b7a0aca` + **`d637cfe9`** (семантический порт кандидата, 8 файлов) + **`95526863`** (bump 2.58.85, 31 файл) = **39 файлов дельты** |
| Push | `git push -u origin release/win-glass-2.58.85` (обычный, без force); `ls-remote` = 95526863… |
| Сервер | fetch (1-я попытка OK), `git checkout -B release/win-glass-2.58.85 origin/...`; HEAD `95526863`, TRACKED_MOD_AFTER=0, UNTRACKED=13 (не тронуто) |
| MUTABLE_WORKTREE_REQUIRED | **no** — деплой из immutable закоммиченного дерева; main worktree (master/WIP) не тронут; write scope релиза = только release-ветка/worktree в scratch |
| DDL / миграции | ΔDDL = 0, миграций нет |
| Версии | 2.58.84 → **2.58.85** (settings + README + F8-meta (HEAD `d637cfe9`) + 24 py-пина + 4 JS-пина = 31 файл, конвенция fs-релиза) |
| Rollback | **`0b7a0aca`** = `release/fs-2.58.84` (2.58.84), ветка на сервере присутствует; DDL-откат не нужен |

## Семантический порт (что именно приехало; отклонение от «байт-переноса»)

Кандидат `0ca661fe` собран на master-линии (base `8e326403`); её `web/app.js`/`web/index.html`
несут ~1.3k строк SOUL-1/W7, которых на прод-линии нет. Байт-перенос утащил бы чужие фичи,
поэтому применён семантический порт (прецедент fs-релиза `a4fb04a9`): патчи `8e326403..0ca661fe`
по 5 файлам применены `git apply` на ПРОД-блобы — **все 5 rc=0, numstat каждого файла совпал
с кандидатом** (106/2, 5/0, 18/0, 32/12, 23/12), паритет токенов хотфикса кандидат↔релиз
(`_applyRefractLayer` 2=2, `_syncGlassRefraction` 4=4, `data-refract-layer` 6=6/4=4,
`__GlassRefraction` 8=8, index 1=1). 3 новых файла взяты байт-в-байт.

| Файл | Кандидат sha256_12 | Релиз sha256_12 | Статус |
|---|---|---|---|
| `web/static/glass-refraction.js` (new) | `6a09d962d59d` | `6a09d962d59d` | byte-equal |
| `web/static/glass-probe.js` | `b2e6a1f987c6` | `b2e6a1f987c6` | byte-equal |
| `tests/js/glass_refraction_test.js` (new) | `4fc4f9ca7848` | `4fc4f9ca7848` | byte-equal |
| `tests/js/glass_probe_test.js` | `bed0d1dfca67` | `bed0d1dfca67` | byte-equal |
| `tools/ui_win_glass_refraction_e2e.py` (new) | `612200f86b84` | `612200f86b84` | byte-equal |
| `web/app.js` | `5a810c0f4443` | `6c3edf36a238` | порт (ханки идентичны) |
| `web/static/app.css` | `3c67a414da7b` | `c01916cf3ef5` | порт (ханки идентичны) |
| `web/index.html` | `0971d49d5337` | `4830df0b4049` | порт (ханки идентичны) |
| `web/static/fullscreen-policy.js` | `96db06425079` | `96db06425079` | byte-equal, не тронут |

## Изоляция (доказательства)

1. **Дельта vs `0b7a0aca` = ровно 39 файлов: 8 порт + 31 бамп, 0 неклассифицированных, пересечение 0**
   (`isolation-classification.txt`; `delta-files-with-stats.txt`).
2. **SOUL byte-diff ПУСТ**: `git diff 0b7a0aca..95526863 -- <22 SOUL-пути>` → 0 байт
   (`soul1-diff-empty.txt` + `soul1-diff-empty-len.txt`: 11 путей существуют на линии, 11 отсутствуют
   по обе стороны). SOUL-1-only файлы отсутствуют и untracked (`soul1-absent.txt`, 11/11 NO).
3. **Маркеры на релиз-дереве**: `speechLessonAction`, `ai/speech`, `initiative-vitality`,
   `initiativeVitality`, `embeddings-primary`, `cr.key_source`, `@app.get("/api/speech` → **0**;
   live fs-отрицания в `web/` (`data-fs-diagnostics`, `fsReasonText`, `fsNextStep`, `fsDiag`,
   `tdesktop_disabled_until_e2e`, `_softExitTimer`, `launchExitIgnored`, `fs-slot-float`) → **0**
   (остальные упоминания — негативные assert'ы предсуществующих тестов и исторические доки
   `plans/**`, дельтой не тронуты) (`soul1-markers-release-tree.txt`).
4. **Frozen-check** (адаптированная копия `tools/soul1_w4_frozen_check.py`; BASE=`0b7a0aca` вместо HEAD,
   OUT→scratch): все 8 маркеров (lg-lens/feDisplacementMap/polygon-background.js/--lg-tint-hero/--lg-blur/
   glass-card) `same`, `index.html`/`app.js` LF-only → **FROZEN-ASSETS-OK** (`frozen-assets.txt`).
5. Серверные проверки: `SPEECH_ABSENT=1`; `REFRACT_APPJS=6`, `REFRACT_CSS=4`, `REFRACT_INDEX=1`,
   `PROBE_LAYER=8` (см. `deploy-run.txt` §F).

## Тесты на точном релиз-кандидате (verbatim; все — на дереве ветки)

| Прогон | Результат | Артефакт |
|---|---|---|
| Все node-сторожа `tests/js/*.js` (85 файлов на релиз-линии) | **84/85 OK**, 1 предсуществующий RED | `node-guards.txt` |
| RED: `round1025_design_tokens_test.js` | `TypeError: this._lgGlassSelector is not a function` — **воспроизведён на чистом `0b7a0aca` идентично** (const-diff по файлу = 0) | `design-tokens-base.txt` / `design-tokens-release.txt` |
| WIN-GLASS e2e (`tools/ui_win_glass_refraction_e2e.py`) | **37/37 (A21/C4/B10/D2), WG-REFRACT-E2E-OK**; смещение −26/+32 device px (corr 0.92/0.971), центр 0 (corr 1.0), шум OFF↔OFF 0/0 | `e2e-run.txt` + `e2e/_results.json` + 5 PNG |
| 24 py-пина (после bump) | **866 passed / 2 failed** | `pytest-24py-pins.txt` |
| 2 RED — bounds-сторожа (`TestBounds::test_forbidden_paths_out_of_diff`, `TestBoundsA3::..._vs_baseline`) | гэп NOTE-санкции кандидата (см. Девиации §3) | `bounds-guard-red.txt` |
| `tools/gen_param_registry_round1025.py --check` | `CHECK OK: реестр 572 == REGISTRY, ...` | `gen-registry-check.txt` |
| Локальный смоук страницы | покрыт e2e (реальные байты, стабы API) + пост-деплой headless ниже | — |

## Прод-верификация (всё с сервера; полный лог `deploy-run.txt`)

- **Артефакты**: `sha256sum` 7/7 == расчётным (`glass-refraction.js` `6a09d962d59d`,
  `glass-probe.js` `b2e6a1f987c6`, `app.js` `6c3edf36a238`, `app.css` `c01916cf3ef5`,
  `index.html` `4830df0b4049`, `fullscreen-policy.js` `96db06425079`, `settings.py` `4d8dd03a3f63`);
  `APP_VERSION="2.58.85"`.
- **Рестарт**: `SUDO_NOPASS=0` → пароль через `sudo -S` (скраб), `RESTART_RC=0`; healthz в цикле →
  `{"status":"ok","version":"2.58.85"}` (процесс стартовал 21:05:16Z, health — 21:05:2xZ).
- **Пробы (сервер, loopback)**: 10/10 URL → 200 (`/healthz`, `/static/glass-refraction.js`,
  `/static/glass-probe.js`, `/static/app.css`, `/web/`, `/web/app.js`, `/web/static/app.css`,
  `/web/static/glass-refraction.js`, `/web/static/glass-probe.js`, `/web/static/fullscreen-policy.js`);
  страница `/web/`: `glass-refraction.js` 1×, `2.58.85` 15×.
- **Журнал**: старт чистый (роутеры, воркеры, `Run polling for bot @PERMsoc_bot`, ingestion живой);
  `ERROR|CRITICAL|Traceback` = **0**; `MainPID=3232336`, `NRestarts=0`, `ExecMainStatus=0`,
  active/running.
- **Извне (мой хост)**: `https://admin-bot.duckdns.org/healthz` → 200 `2.58.85`;
  `/static/glass-refraction.js` 200 (31744 b, sha `6a09d962d59d`); `/web/app.js` sha `6c3edf36a238`;
  `/web/static/app.css` sha `c01916cf3ef5`; `/web/static/fullscreen-policy.js` sha `96db06425079`;
  `/web/` — 15×`2.58.85`, 0×`2.58.84` (`postdeploy_http.txt`).
- **Headless Chromium 390×844** (plain browser): 200, 0 ошибок консоли/страницы;
  `window.__GlassRefraction`/`__GlassProbe`/`__FullscreenPolicy` = object; script-тег на месте
  (`postdeploy_probe.json`, `postdeploy_390.png`).
- **deployed_commit для ре-анкора**: **`9552686391dfe69dd7cb08ba7cd800a8a6c5106e`** (релиз-линия);
  привязка карты остаётся к кандидату `0ca661fe` (порт-мэппинг — в таблице выше; мапу не менял).
- DDL/БД: не затрагивались (web-only изменение).

## Rollback (готовность; не потребовался)

```bash
ssh nik@198.46.175.136
cd /var/www/admin_bot
git checkout release/fs-2.58.84        # 0b7a0aca = 2.58.84 (ветка на сервере есть)
sudo systemctl restart admin_bot
curl -s http://127.0.0.1:8000/healthz  # ожидаем {"status":"ok","version":"2.58.84"}
```
Резерв: `git checkout --detach 0b7a0aca416a418e099e157eca77d0a3137b3405`. DDL-откат не нужен.

## SSH-коннекты (дисциплина AGENTS.md)

**2 логина**, оба одиночные, успешные: (1) recon 21:04:18Z (~4 c, `RECON_OK`); (2) основной прогон
21:04:5x–21:06Z (A→F, рестарт, health, пробы, журнал). Ретраев нет; порт был открыт (бана нет);
пароли не печатались — автоскраб раннера, контроль утечек: 0 вхождений в лог.

## Девиации (честно)

1. **Семантический порт вместо байт-переноса**: 3 файла (`app.js`/`app.css`/`index.html`) — прод-база +
   идентичные ханки кандидата (проверено numstat/токенами); 5/8 файлов — байт-в-байт. Причина: master-база
   кандидата содержала нерелизованные SOUL-1/W7 (+~1300 строк в каждом из двух файлов) — перенос байт
   нарушил бы изоляцию релиза. Прецедент: fs-релиз (`a4fb04a9`).
2. **Node-число**: ожидалось «87/87» (master-значение); на релиз-линии сторожей 85 (84 прод + 1 новый),
   результат 84 OK + 1 предсуществующий RED `round1025_design_tokens_test.js` (тот же RED был на
   задеплоенном 448cc81a и в fs-релизе; воспроизведён на чистом `0b7a0aca`, идентичная сигнатура).
3. **2 bounds-сторожа RED (гэп кандидата, не порта)**: новый `web/static/glass-refraction.js` не внесён
   в NOTE-санкционный allowlist сторожей (`tests/test_tool_coordinator_round1026.py`,
   `tests/test_unified_image_request_round1026.py`); на master-линии санкции тоже нет. База `0b7a0aca`
   проходит 2/2, релиз-тип фейлит 2/2. Продукт не затронут (test-only). Готов предложенный патч
   (`bounds-guard-sanction-suggested.patch`, `git apply --check` rc=0, зеркалит прецеденты
   `da58e24b`/SOUL-1 W6) — **в задеплоенное дерево НЕ включён** (вне скоупа «только кандидат+бамп»),
   требует ратификации Builder/Reviewer или решения леджера.
4. **Стоп-строки журнала** (graceful-stop старого процесса) не попали в окно `tail -45`: захвачен старт
   нового процесса; грациозность подтверждается healthy-состоянием, 0 ошибок, `NRestarts=0` и
   сигнал-хендлерами нового процесса; контракт стопа валидирован fs-релизом (тот же механизм).

## Evidence

`plans/features/win-glass-hotfix/evidence/release/`: `branch-log.txt`, `delta-files-with-stats.txt`,
`isolation-classification.txt`, `soul1-diff-empty.txt` (0 байт) + `soul1-diff-empty-len.txt`,
`soul1-absent.txt`, `soul1-markers-release-tree.txt`, `hashes.txt`, `node-guards.txt`,
`design-tokens-base.txt`, `design-tokens-release.txt`, `e2e-run.txt` + `e2e/**` (5 PNG + `_results.json`),
`frozen-assets.txt`, `pytest-24py-pins.txt`, `gen-registry-check.txt`, `bounds-guard-red.txt`,
`bounds-guard-sanction-suggested.patch`, `recon.txt`, `deploy-run.txt`, `postdeploy_http.txt`,
`postdeploy_probe.json`, `postdeploy_390.png`.
Скрипты/ветки: `OPENCODE_WORKFLOW_SCRATCH/win-glass-release-25885/` (`bump_25885.py`, `deploy_25885.py`,
`gen_hashes.py`, `gen_release_evidence.py`, `node_sweep.py`, `run_e2e.py`, `run_pypins.py`,
`frozen_check_25885.py`, `postdeploy_probe.py`, `patch_guard_suggest.py`); worktrees `wt/` (release)
и `base-check/` (чистая база 0b7a0aca).

## Live (НЕ VERIFIED — за владельцем)

7 RFL-строк: `WG-WIN-02/03/05`, `WG-ANDROID-02`, `WG-VER-01/02`, `WG-P0-05` — наблюдения владельца по
`owner-steps.md` (Windows: обход §A.1 + снимок админ-диагностики; Android: видимое смещение у кромок,
перф/скролл/поворот; опц. iOS). Release-стадия гейта не запускалась (ждёт живые наблюдения);
map не менял; re-anchor `deployed_commit` — за parent/PM/леджером.

## Леджер (WG-LEDGER, 2026-10-18; добавлено после релиза)

- Артефакты релиза закоммичены (этот отчёт + `evidence/release/**`).
- Ре-анкор карты: `deployed_commit := 9552686391dfe69dd7cb08ba7cd800a8a6c5106e`, `candidate_commit`
  остаётся `0ca661fe` — **двухлинейная семантика** (семантический порт `d637cfe9` на прод-линию;
  конвенция как в soul-картах). Пометка о двух линиях: `evidence/verify/release-line.txt`.
- Карта release-стадию гейта не проходила: 7 RFL-строк ждут owner-наблюдений по `owner-steps.md`
  (plan- и review-стадии после ре-анкора — errors=0 на трёх слайсах).
