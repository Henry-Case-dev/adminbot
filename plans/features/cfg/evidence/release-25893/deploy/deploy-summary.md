# DEPLOY-25893 — evidence: выкат 2.58.93 (CFG-02C) + пост-смок

Релиз: **2.58.93** — CFG-02C (жёсткая изоляция бюджетов `user_image` ↔ `summary_cover`,
shared-only резерв обложек, честный `shared_budget`, витрина «Пользовательские изображения»).
Утверждённый кандидат: `b4d30cab364e920d453d2d6a2afe2f95e1c24834` (= `origin/master`,
review-коммит `b4d30cab`; bump `74160a5d`, код CFG-02C `1d9a7107`).

- Прод ДО: `1d367e4c` (2.58.92, healthz 2.58.92) → ПОСЛЕ: `b4d30cab` (2.58.93).
- **Server-reported HEAD после выката = `b4d30cab364e920d453d2d6a2afe2f95e1c24834`** — совпадает
  с утверждённым кандидатом (подтверждено дважды: J-стадия деплоя и пост-смок).
- DEPLOY_SOURCE: `origin/master` (иммутабельный коммит); mutable worktree не требуется.
- Инструменты: `deploy_25893.py` sha256_12 `ab71cc472dd7` (режимы recon/main, 1 SSH-коннект
  на режим, без ретраев); `rel93_final.sh` `9b10fa2875b4` (read-only probe); пост-смок
  `smoke93_readonly.py` `ae1b042919b9` (read-only, 1 коннект).

## Режимы и rc

| режим | rc | результат |
|---|---|---|
| recon | 0 | SSH жив, прод `1d367e4c`/2.58.92, 06:39:03Z |
| main | 0 | checkout `b4d30cab`, restart, healthz 2.58.93, J-стадия OK |
| post-smoke (read-only) | 0 | журнал/маркеры/served/миграции — все ожидания сошлись |
| gate release (read-only) | 1 | **ожидаемо**: карта привязана к `1d9a7107` и имеет READY_FOR_LIVE (§Ф6 — след. волна); карта лейном не правилась |

T0 (рестарт, UTC): **2026-10-19 06:41:08**. MainPID: 3548159 → **3635488**
(NRestarts=0, active/running, ExecMainStartTimestamp 06:41:22Z).

## Ключевые проверки (main + post-smoke, 06:41:52Z / 06:46:04Z)

- healthz loopback **и** HTTPS = `2.58.93`; маршруты HTTPS 200/200/200.
- Изоляция дельты: `DELTA_RUNTIME` = 9/9 == whitelist (set-eq), `DELTA_TOTAL`=118,
  `TRACKED_MOD_AFTER`=0; `EXPECT12` хэши **14/14**; `APP_VERSION="2.58.93"`.
- Маркеры CFG-02C 15/15 по ожиданиям; регрессионные маркеры 2.58.92/2.58.91 на месте.
- Журнал since T0: ERR/CRITICAL/Traceback=**0**, RuntimeWarning=0, `402`=**0**
  (raw-выборка ERR/402 пуста), SKIPS=**0**, GRACEFUL=2, POLLER=1.
- Маркеры журнала CFG-02C: `COVER_JOURNAL`=0, `SHARED_BUDGET_DENY`=0 (в окне не было
  cover-активности — изоляцию бюджета в живом сценарии доказывает §Ф6-волна);
  `SCOPE_LABEL_SERVED`=**1**.
- Served: `SERVED_EQ_APP_JS=SAME`, `SERVED_EQ_APP_CSS=SAME`, `PAGE_VER`=**15**,
  `SUBST_CSS`=**2**.
- Дрифт=0: `TRACKED_MOD`=0, `DRIFT_TO_ORIGIN`=0, A-pre `PROD_RUNTIME_DRIFT`=0.
- Миграции: `pending=[]`, `user_version=36` (ΔDDL=0), migrations `complete`.

Warnings: нет (WARNINGS-SUMMARY пуст; tree-restore/rollback не запускались).

## Откат

- Abort до рестарта: `_tree_restore` → прод-линия `release/fix-2.58.92` @ `1d367e4c`
  (запушена; fallback — detach `1d367e4c`) — **не потребовался**.
- Abort после рестарта: авто-рубеж `release/cfg1-2.58.88` (2.58.88) — **не потребовался**.
- Готовность отката сохраняется: `release/fix-2.58.92` (1d367e4c) и `release/cfg1-2.58.88`.

## Остаток

- **§Ф6-приёмка (a)–(f)** — следующая волна (витрина CFG-02C.5 live, изоляция live без
  траты бюджета, shared-honest, экономика/журнал, уборка). Пункты карты в статусе
  `READY_FOR_LIVE` остаются за ней; родительская волна перевяжет release-gate.

## Файлы (sha256_12)

- `ev01-recon.txt` `19d161004401`; `ev02-deploy-run.txt` `92f2221b3b30`;
  `ev03-final-verification.txt` `25e97d512cfe`; `ev04-post-smoke.txt` `0a0557815da7`;
  `ev05-gate-release-check.txt` `e59879171a26`.

Примечание: read-only API-пробы без TMA-заголовка вернули `{"detail":"missing init data"}`
(ожидаемая auth-заглушка, не дефект). `UNTRACKED=13` на проде — pre-existing.
