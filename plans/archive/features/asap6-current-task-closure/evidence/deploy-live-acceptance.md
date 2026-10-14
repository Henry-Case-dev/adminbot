# ASAP 6 Deploy + Live Acceptance Evidence (08.10.2026)

## Deploy
- Commit: bbfd8fb (push ff f1c78ce..bbfd8fb, без force), 99 файлов, +18556/−12298
- Прод pull --ff-only: HEAD = bbfd8fb; рестарт x2; is-active=active
- healthz: {"status":"ok","version":"2.58.70"}
- Boot-лог: ERROR/CRITICAL/Traceback=0, locked=0, vision-воркер жив
- Unauth RBAC smoke: /api/info 401, /api/info/guide 401, /api/oversight/runs 401, /web/ 200
- Живой mca_event в прод-логе (MCA-17): mca_event=message_revision | outcome=skipped | reason_code=source_missing — новый контур телеметрии течёт
- DDL: 0 (v33 не менялась), миграции не вызывались

## ANU Quantum — live acceptance VERIFIED
- 14:41:46 startup | {'status': 'blocked', 'reason': 'provider_unconfigured'} (до)
- test_connection (прод-скрипт, hot_config.set_config_cache + SQLite DatabaseService): healthy=True, state='active', key_present=True, persisted=True, length=1024, latency_ms=594
- 15:04:20 startup | {'status': 'ok', 'remaining': 1023} (после — бот подхватил ключ, self-check draw учтён)
- Ключ владельца сохранён через protected secret path (bot_settings, config_cache.set), plaintext не в логах/отчётах; временные файлы /tmp/.anu_* удалены

## Summary live-run
- По расписанию (cron 0,6,12,18 UTC — ближайший 18:00 UTC); dry-run endpoint требует auth-контур владельца
- Предпосылки VERIFIED: код 2.58.70 на проде, quote-state фикс в горячем пути (12586-тестов), миграций нет

## UX
- Status/Analytics: Playwright (19/19, desktop 1280x800 + mobile 390x844) + Browser Use (визуальный осмотр) — локально на real-рендере; прод /web/ 200; скриншоты evidence/ (17+3)
- Поправка владельца (логи = anchor, не вкладка) — реализована, RED→GREEN

## Остатки (честно)
- MCA-23 фаза 2: multi-tool DAG, ResponseDocument, planned-vs-actual, Golden E2E A-R, Help re-sync — in_progress (запрет закрытия «остатками в backlog»)
- Summary live-run по расписанию: проверить лог после 18:00 UTC (команда: journalctl -u admin_bot --since '18:00' | grep -E 'SUMMARY_|L1_|L2_')