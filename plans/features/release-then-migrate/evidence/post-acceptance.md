# POST-ACCEPTANCE + SWITCH — release-then-migrate (§7.1 расширенная приёмка нового production, DevOps)

**Дата:** 2026-10-29, окно наблюдения 04:44–05:00 UTC (cutover завершён 04:17:39Z; окно естественной активности на момент проверок ≈27–43 мин).
**MIGRATION_SOURCE_SHA:** `5346ee765e83ee859596b60437811b21db1e4564` (2.58.141) — подтверждён на NEW (git HEAD, N1-S0); соответствует принятому релизу: merge `0ef8477b` кандидата `0b8dfe6a` + bump, код байт-идентичен ревью-кандидату (blob-пины 10/10, DEPLOY-258141). **Соответствие принято — PASS.**
**Тестовые сообщения в рабочие чаты не отправлялись.** Платные live-вызовы (LLM/факт-чек/генерация изображений) не выполнялись — только контракт/конфиг/данные и изолированные non-delivery пробы.

## 0. Журнал сеансов (fail2ban-дисциплина: single auth, без ретраев/параллели, пейсинг ≥62 c/хост)

| # | Время UTC | Хост | Содержание | Результат |
|---|---|---|---|---|
| ext | 04:44:06 | локально (без SSH) | DNS×3, TLS, healthz/api/admin, 401-слой, скан портов, старый IP | OK |
| N1 | 04:45:09 | NEW | основной read-only батч §7.1 (S0–S10) | rc=0 |
| N2 | 04:48:51 | NEW | добор проб (L1/L2, roles, embedding-index, FTS, vec0) + **единственный управляемый `systemctl restart admin_bot`** | rc=0 |
| O1 | 04:54:29 | OLD | fallback-состояние + parity-пробы (ffmpeg, пре-существенность warning'ов) | rc=0 |
| N3 | 04:55:21 | NEW | fail2ban (SWITCH) + ffmpeg (parity) + KNN по боевой vec0-таблице | rc=0 |
| ext2 | 04:58 | локально | HEAD подписанных media-URL (найдено 0 — нечего пробовать) | OK |

Fingerprints: NEW `ssh-rsa SHA256:KMOAKfeddYbWXoqx7W4mVgu+DaU2Qg+V0wF5CRmHYAg` == INV/PREP-эталон; OLD `ssh-ed25519 SHA256:pRCrZUI6c1K7iPEVUpycCEcqNVRAKHeklX3nHpe/sjI` (стабилен). Креды — только из `deploy_commands.txt`, в память; raw-логи санитизированы.

## 1. Таблица §7.1 — `компонент | старый production | новый production | evidence | status`

| Компонент | Старый production | Новый production | Evidence | Status |
|---|---|---|---|---|
| Версия/код | 2.58.141 @ 5346ee76 (принято, DEPLOY-258141) | 2.58.141 @ 5346ee76 (HEAD; dirty=1 — untracked `.cache/`, классифицировано в CUT) | N1-S0; ext | **PASS** |
| Единственный production | admin_bot inactive+**disabled**, 4 контейнера Exited, 0 bot/bot-api procs | 1×bot.py, 1×bot-api, единственный poller («Run polling» 04:17:38), 409/conflict=0 | O1; N1-S2, N2-R4 | **PASS** |
| Deploy-таргет | fallback (НЕ деплоить) | единственный деплой-таргет: `deploy_commands.txt` + репо `AGENTS.md` обновлены (SWITCH §3) | артефакт §3 | **PASS** |
| systemd | admin_bot disabled | active+enabled, NRestarts=0 (0 неожиданных рестартов), управляемый рестарт: graceful stop 251 мс → healthz **try1** ≈5 c, NRestarts остаётся 0 (ручной рестарт счётчик не инкрементирует — семантика записана), новый MainPID 68406, данные монотонны | N1-S1; N2-R1–R3 | **PASS** |
| Docker | 4×Exited | postgres healthy (127.0.0.1:5432), telegram-bot-api healthy (127.0.0.1:8081), cobalt healthy (loopback:9000), bgutil Up (:4416, снаружи закрыт ufw) | N1-S3/S4; N2-R5; ext-скан | **PASS** |
| Служебные порты снаружи | — | 5432/8081/9000/10808/4416/8000 → **CLOSED** извне; открыты только 22/80/443 | ext | **PASS** |
| SQLite данные | снапшот-эталон (freeze 04:06–04:11Z) | integrity ok (16.7 c), user_version 37, 121 таблиц; smart_messages 2 050 132→**2 050 145** (+13, max_rowid 2 372 360→2 372 373 MONOTONIC), mca_events 136 967→137 029 (+62), graph_facts **21 688 =**, nodes **28 964 =**, edges **52 598 =**, embedding_cache **16 649 =**, mca_episodes **23 =**, experience_episodes **449 =**, dream_log **1 521 =**, nostalgia_log **414 =**, message_source 66 834→66 846 (+12), summary_runs **28 =**, task_jobs 7 650→7 659 (+9, stuck/active=0) | N1-S6; N2-R0b/R3 | **PASS** |
| Выборочные чтения памяти | источник данных | alias→user_id: маппинг author_name→user_id читается (3 пары) + mca_self_identity (bot_user_id bound, n=1); **KNN по боевой graph_facts_vec**: 5 соседей за 0.60 c (vec0, 21 771 строк, генерация 2 active, dims 3072); FTS MATCH ≤5 строк за 0.00 c; Golden Facts (protected_facts) =1, читается; L1 running_summary =1 (raw_count 500); L2 levels — **0 строк (состояние 1-в-1 со старым, перенос байт-снапшотом)**; последние сообщения читаются (id/ts/len, без текстов) | N1-S6; N3-F5 | **PASS** |
| PostgreSQL | дамп-эталон (25 equal + uptime) | bot_settings **544 =**, chat_profiles **3 =**, personas **2 =**, persona_traits **50 =**, chat_lore_history **250 =**, uptime_events 4297→4323 (heartbeat 60 c, «up», last 04:44:37Z), llm_usage 9387 (+10), image_reservation **14 =**, worker_budget **311 =**, anticliche_cache **1 =**, cover_* на месте (assets 13, issue_assignments 106, profiles 1) | N1-S7 | **PASS** |
| Админка | 200 (307→/web/) | `/` 307→`/web/` 200 (внешне и локально); TMA-слой жив: /api/config, /api/me → **401** без initData; роли 4 (admin/moderator/user/local_admin с permissions), bot_admins 3, per-chat профили 3; сохранённые провайдеры/промпты: 20+ ключей `prompts.*` + при каждом старте «кастом юзера — НЕ трогаем» ×11 (промпты защищены и на месте); настройки = снапшоту (544) | ext; N1-S7/S10; N2-R4 | **PASS** (логин реальным TMA-клиентом — owner-side; агентски проверены слой auth и данные) |
| Текущая задача (p0-history-analysis) | принято ревью на старом | read-only проба пути инструмента на прод-БД: requested=150 → available=150 (**без клампа**), стр.1 fetched=40; requested=60 → 60/40; FTS-путь жив; естественная строка `fetched=…` в журнале за окно — NOT_OBSERVED (tool-вызовов не было) | N1-S6 (HIST-пробы) | **PASS** (проба) / NOT_OBSERVED (естественная линия — ждать реального трафика) |
| Прикладные маршруты (конфиг/данные) | то же | Direct/L1: конфиг+промпты на месте, событийной активности за окно не было (NOT_OBSERVED live); ToolRouter+поиск: FTS-проба мгновенная; Fact-check: промпты/ключи/лимиты на месте (live не звали — платно); Summary: env+PG-флаги+история runs на месте (расписания настроены, forced run не звали); Initiative: конфиг на месте + **observer tick каждые 5 мин executed successfully** (живой); Nostalgia: конфиг+лог 414 =; Vision/media: флаги+ключи, cobalt/bot-api healthy; генерация изображений: контракт на месте (флаг+IMAGE_API_KEY), live не звали | N1-S5/S7/S8; N2-R4 | **PASS** (конфиг/данные/тик-механика); live-LLM-пути NOT_OBSERVED (естественных событий за окно не было, платные вызовы запрещены) |
| Фоновые тики | расписания | initiative_observer: 4 тика ✓; summary/dream/consolidation циклы за 27-мин окно НЕ наступили (расписания длиннее окна) — состояния в БД на месте, билд-задания отсутствуют (active=0) | N1-S5 | частично: PASS / **NOT_OBSERVED** (циклы) |
| Журнал с cutover | эталон классов | 879 строк; **ERR=4 — все одно pre-existing событие**: wikipedia-403 anticliche fetch (04:22:37, известный класс); WARN 15: embed `NameError`+FTS-only smart_archive — **пре-существующие** (на OLD за 2 дня: 124 и 26 соответственно, O1); prompt_migration «НЕ трогаем» ×11 (благоприятно); ffmpeg-варнинг — причина устранена (§2.1) | N1-S5; N2-R4; O1 | **PASS** |
| Домен/DNS/TLS | A → 198.46.175.136 (снята), :443 refused | DNS (1.1.1.1/8.8.8.8/9.9.9.9) → **только 192.255.209.205**; TLS LE **VALID** (CN=admin-bot.duckdns.org, notBefore 29.10 03:15Z, notAfter 27.01.2027); healthz 200 `2.58.141`; /api/health 200; / и /web/ 200 | ext; O1 | **PASS** |
| Публичные media URLs | 59 файлов (бит-в-бит перенесены) | 59 файлов на месте; `media/share` отсутствует — **опубликованных файлов сейчас нет** (на заморозке тоже не было; публикация эпизодична, TTL); маршрут жив и подпись обязательна (bogus → 405/403, не 200); секрет подписи в PG присутствует | N1-S9; ext; ext2 | **NOT_OBSERVED** (файловый HEAD — нечего подписывать); маршрут/подпись PASS |
| fail2ban | active+enabled (исторический) | установлен, active+enabled, jail sshd (bantime 1h, findtime 10m, maxretry 5, backend systemd для Ubuntu 24.04); уже 1 бан сканера; single-connect скрипты не банятся | N3; O1 | **PASS** |

## 2. Контрольные суммы/числа и аномалии

### 2.1 Числа БД (снапшот freeze → NEW сейчас)
SQLite: 2 050 132→2 050 145 smart_messages (MONOTONIC +13), остальные структурные счётчики **равны** снапшоту (§1, строки «SQLite данные»/«PostgreSQL»); integrity_check ok; контрольные суммы байт-уровня сверялись при загрузке cutover (sha 4/4 MATCH, cutover-retry §2) — здесь приведены числовые дельты живой активности. PG: все 9 exact-каунтов == снапшоту, рост только uptime_events (heartbeat) и llm_usage_events. Никаких импортов/пересборок памяти не выполнялось (проверено: index generations 3 =, embedding_cache 16 649 =).

### 2.2 Аномалии (все классифицированы)
1. **ffmpeg отсутствовал на NEW** (на OLD `/usr/bin/ffmpeg` был) — merge yt-dlp падал бы. **УСТРАНЕНО** (N3: apt install ffmpeg — инфра-паритет, код не менялся). Инфра-дельта миграции, не продукта.
2. **`embed transport error | NameError` + smart_archive FTS-only (gen building)** — **пре-существующие** на старом проде (O1: 124 и 26 вхождений за 2 дня), перенесены как есть; не регрессия миграции. Builder-область, вне среза — в backlog как incidental.
3. **caddy/xray на OLD enabled (inactive)** — при гипотетическом ребуте старого поднимутся только прокси (admin_bot disabled, двойного бота не будет); оставлено сознанно для rollback.
4. **chat_summary_levels = 0 строк** — состояние данных 1-в-1 со старым (байт-снапшот), потерей не является.
5. **graph_facts_vec 21 771 строк vs graph_facts 21 688** — внутренняя форма vec0-индекса (superseded/история), состояние старого прод-сервера, KNN обслуживается.

## 3. SWITCH (4 строки карты) — выполнено
1. **Deploy target** (`deploy_commands.txt`, приватный, вне Git): заголовок-селектор обновлён — НОВЫЙ VPS = единый production (деплой `git pull --ff-only` + `systemctl restart admin_bot` там), СТАРЫЙ = остановленный fallback с явной пометкой «НЕ деплоить»; креды обеих секций сохранены без изменений, значения нигде не напечатаны.
2. **`AGENTS.md`** (репо): инфра-секция обновлена минимально — production с 29.10.2026 = 192.255.209.205, старый = fallback для отката, fail2ban на ОБОИХ, логины из приватного файла.
3. **fail2ban на NEW**: установлен/включён сейчас (jail sshd, sane defaults, backend systemd — Ubuntu 24.04 без /var/log/auth.log); проверено: jail активен, 1 бан уже есть, SSH-скрипты с одиночным логином безопасны (все сеансы этого окна — single auth, банов на нас нет).
4. **Цикл DevOps**: git-цикл неинтерактивности доказан в срезе GIT (PREP §7); рестарт-цикл доказан управляемым рестартом N2; следующий обычный деплой попадает на NEW (селектор + AGENTS.md указывают туда). Очередь разработки не останавливалась.

## 4. Raw-evidence
`WorkspaceData/runs/c742e4de9e92c489/release-then-migrate-02338e6f0d2c/temp-025dafe681/`: `post_driver.py` (креды в память, санитизация, пейсинг), `scripts/{n1_post,n2_restart,n3_fail2ban,o1_oldfallback}.sh`, `raw/*.out.txt|*.err.txt|*.meta.json` (все сеансы sanitized).

## 5. Итог среза POST+SWITCH (DevOps)
- §7.1: **критических регрессий нет**; потеря данных/настроек не обнаружена (структурные счётчики == снапшоту, рост только живой); сервисы здоровы; единственный production; деплой-таргет переключён.
- Честные NOT_OBSERVED (future-dependent, не блокируют — окна естественных событий ещё не наступали за ~30–45 мин): естественная строка `fetched=` от get_recent_history; summary/dream/consolidation циклы по расписанию; файловый HEAD публичного media-URL (нет опубликованных файлов); логин в админку реальным TMA-клиентом; live-LLM-пути (запрещены платные вызовы).
- Управляемый рестарт: чистый (graceful 251 мс, healthz try1, без потери данных, polling восстановлен).
- SWITCH: deploy_commands.txt + AGENTS.md обновлены, fail2ban на NEW включён, ffmpeg-паритет восстановлен.
- Готово к PM-байнду строк POST (8) + SWITCH (4) на этот артефакт.
