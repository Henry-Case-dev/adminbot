# REL-25890 — деплой 2.58.90: сводка прогона (18.10.2026, UTC)

- Лейн: DEVOPS-DEPLOY-90 — деплой + минимальный read-only пост-смок; приёмка §4 — отдельная следующая волна.
- Кандидат: `3b02366e63022eb4c760892aa1bcb4f26516e789` (origin/master; GitHub `ls-remote` совпал; bump `f2cd3a71` — ancestor).
- Скрипты: `deploy_25890.py` sha256_12 `2d47290eeeb0`, probe `rel90_final.sh` sha256_12 `c4e74d87e477` — равны ревью-биндингам; пере-сверены до и после прогона (без правок).
- Режим `main`: ровно ОДИН SSH-коннект (fail2ban-дисциплина; отдельный recon не выполнялся — pre-state покрыт шагом A), без ретраев и параллельных коннектов.
- Итог: **DEPLOY_RC=0**; откат не потребовался (ни `_tree_restore` до рестарта, ни `_rb` после — не срабатывали); предупреждений нет (`WARNINGS-SUMMARY` отсутствует).

## rc по шагам — все rc=0

| шаг | ключевые наблюдения |
|---|---|
| A_pre_state | NOW_UTC=2026-10-18T13:34:11Z; HZ_BEFORE=2.58.89; OLD_HEAD=`d59fab94` (ветка `release/fix-2.58.89`); TRACKED_MOD=0; PROD_RUNTIME_DRIFT=0; INDEX_LOCK=absent; MainPID(старый)=3359708 |
| B1_fetch | FETCH1_RC=0; `31c16555..3b02366e master -> origin/master` |
| B3_remote_ref | origin/master = `3b02366e`; BUMP_IS_ANCESTOR=1 |
| C_checkout | CO_RC=0; NEW_HEAD=`3b02366e`; TRACKED_MOD_AFTER=0; DELTA_RUNTIME == whitelist множ. равенство (19/19; чужого runtime нет) |
| D1_hashes | **30/30** artifacts sha256_12 == EXPECT12 (18 payload + 3 bump + 9 sanity) |
| D2_markers | APP_VER=2.58.90; INIT_FRESH=3/ANCHORED=3/OPP=1; NOST_SCEN_A=1; PERSIST_DOCPG=11/PERSIST_409=13; UX_CORECOMPACT=10/GROUPS=1/SAVEBAR=3; CFG02A_SPEECH_ENTRY=1; CFG01_RESOLVER=2; META_HEAD=`01e1cc8d` |
| F1_sudo_probe | SUDO_NOPASS=0 (штатный парольный путь через `sudo -S`) |
| F2_restart | RESTART_T0=**2026-10-18 13:34:23** UTC; RESTART_RC=0; probe `rel90_final.sh` загружен на прод |
| F3_health | HEALTH=`{"status":"ok","version":"2.58.90"}` (опрос до 150×2 с) |
| F4_journal | grep `ERROR\|CRITICAL\|Traceback` since T0 = **0** |
| G_served | SERVED_EQ_APP_JS=**SAME**, SERVED_EQ_APP_CSS=**SAME**; PAGE_VER=**15** (EXPECT 15); SUBST_CSS=**2** (EXPECT 2) |
| J_final | полный вывод — `final-verification.txt` (HEAD=`3b02366e`, BRANCH=master, TRACKED_MOD=0) |

## Версия до/после, сервис, журнал

- **До:** 2.58.89 (`d59fab94`, ветка `release/fix-2.58.89`), MainPID=3359708.
- **После:** **2.58.90** (`3b02366e`, ветка `master`); MainPID=**3430462**, NRestarts=**0**, ExecMainStartTimestamp=13:34:35 UTC, ExecMainStatus=0, ActiveState=active / SubState=running.
- Журнал since T0: ERR=**0**, RUNTIMEWARN=0, GRACEFUL=2, POLLER=1; миграции: `start current user_version=36 | pending=[]` → `complete user_version=36` (0.0 s); `PRAGMA user_version` = (36,) — новых DDL нет.
- Runtime-дрифт к кандидату = **0**: DELTA_RUNTIME == whitelist (19), TRACKED_MOD=0 до/после, 30/30 хешей == кандидату.
- HTTPS-маршруты: `/healthz` 200, `/web/` 200, `/static/app.css` 200; `HTTPS_HZ=2.58.90`.
- Отложенная проверка без SSH: HTTPS `/healthz` = **200**, version=2.58.90 в 13:37:35Z (~3 мин после рестарта; на момент J NRestarts=0 — авто-перезапусков не было).

## Откат (не потребовался)

- Штатный рубеж отката остаётся `release/cfg1-2.58.88` (2.58.88, + graceful-рестарт, оси/данные не трогаются); ближайший альтернативный возврат — прод-линия `release/fix-2.58.89` (2.58.89, `d59fab94`).
- Прод-дерево: ветка `master` @ `3b02366e` (checkout `-B master origin/master` — штатный дизайн скрипта).

## Артефакты прогона

- `deploy-run-tail.txt` — хвост лога прогона с `### F1_sudo_probe` до `=== DONE ===` (полный `deploy-run.txt` — в scratch: `adminbot-ccef72c25768/release-25890/logs/deploy-run.txt`).
- `final-verification.txt` — полный read-only вывод `rel90_final.sh` (шаг J).
- Кандидат-биндинг скриптов: `2d47290eeeb0` / `c4e74d87e477` (до и после прогона идентичны).

## Осталось (следующая волна, не в этом лейне)

- Приёмка §4: (b) real-DB цикл «открыть→изменить→сохранить→reread→reload→effective→restore» по типам настроек; (c) nostalgia live (`scenario=A`, воронка, `nostalgia_log`, `mca_events nostalgia_run`); (d) initiative live (`scan_anchored`, writer/recheck/sent или честный `reason_code`, cursor lag); закрытие live-пунктов карт (`P0A-*` READY_FOR_LIVE/PENDING, live_when=postdeploy).
- Requirements gate (release): `--candidate 3b02366e --deployed-commit 3b02366e` — после выполнения §4.
