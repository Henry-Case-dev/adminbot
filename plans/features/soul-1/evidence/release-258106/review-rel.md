# REV-REL-258106 — ревью релизного поезда 2.58.106 (21.10.2026)

Кандидат: HEAD db2fa706 (бамп 83012fcf, F8-meta штамп edab6582 = голова релиз-дельты; docs 1aadf16b/db2fa706 поверх — прецедент 104/105). База: 2.58.105 @ a6246e33.

## Вердикт

**Approved** → DevOps (родитель НЕ DONE: 14.1/14.2 переворачиваются в VERIFIED только после живых постдеплой-проб).

## Состав (git log a6246e33..HEAD, 10 коммитов)

2f1a49ad (web/api/speech.py, web/app.js, web/index.html, web/static/app.css + tests + evidence), a8d049f3 (services/style_policy.py + tests + evidence), 6f8710a8/20252faa/edab6582 (docs+test: ярлыки карты 14.1/14.2), 4f0ae438 (asap8 tests+evidence, runtime=0), cdb0492f (services/chat_migration.py, 8 строк), 83012fcf (бамп: config/settings.py APP_VERSION + README v-строка + F8-meta + 24 py-пина + 4 js-пина = 31 файл), 1aadf16b/db2fa706 (docs/evidence only). Чужих services/handlers нет; ΔDDL=0, схема v37 (`_SCHEMA_VERSION_HUMOR_SAMPLES = 37` нетронута), database.py/scripts вне дельты.

## Гварды (воспроизведено на HEAD)

F8 `--check` 582==REGISTRY OK; help-sync+js-unit 63 passed; node --check web+tests/js bad=0; ui_soul14_layers_e2e failures=0; payload 6p + telemetry 11p = 17 passed; write_points 1 passed; b126 residuals 6 passed; fingerprint 037080375ac8 == FACTORY_SET_SHA256_12; APP_VERSION 2.58.106. pins24 868p/0f — переиспользован лог PKG-106 (pins24-summary.md, по брифу не перегонялся).

## Миграционный фикс cdb0492f

Дифф = сентинел пагинации бэкапа `-1` → `-(2**63)`: PK-алиас chat_running_summary (PK(chat_id)=rowid) у супергрупп имеет отрицательный rowid, старый фильтр читал 0 строк → конспект переносился без backup. Вызов только из handlers/chat_lifecycle.py (lifecycle-событие миграции чата, НЕ старт сервиса); на проде путь не исполнялся (capture1: s4_chat_id_migrations пуст, read-only 21.10) → поведение деплоя не меняет. Находка была воспроизведена RED (strict-xfail) до фикса (review-exec-tails.md), после — строгий регресс + позитив-гард, 6 passed независимо. Откат деплоя: git checkout release/fix-2.58.105 (создать на a6246e33 при деплое) + рестарт; миграций нет, откат чистый.

## Гигиена

Секрет-скан диффа: 0 реальных кредов (хиты — тестовый стаб, фейковый secret в приватном тесте телеметрии, доки о маскировке). Чужие dirty (glass-tiera PNG, некоммитнутая строка зонтика SOUL-14.0/14.4 в карте, backlog.md) в коммиты не вошли. Ярлыки карты подтверждены в JSON: SOUL-14.1 READY_FOR_LIVE (live_required, preprod, кандидат 2f1a49ad), SOUL-14.2 READY_FOR_LIVE (live_required, postdeploy, кандидат a8d049f3).

## Live-план DevOps (обязательные пробы, read-only)

1. /healthz 200 + APP_VERSION 2.58.106 в статусе.
2. SOUL-14.1 (сразу после выката): GET /api/speech/overview — блок layers (_layers_payload: L1-флаги, SelfModel gate+snapshot counts, честный null при отсутствии данных); в MiniApp «Речь и характер» карточка «Как рождается ответ»: 7 узлов, без данных «—», без выдуманных чисел. Факт/скрин в evidence.
3. SOUL-14.2 (постдеплой): реальный или эмулированный проход style policy (direct/initiative pre-send) → строка event_name='speech_extent', component='style_policy' в mca_events; usage_json R17-safe (extent/status/one_word/words/reason/context, без текстов). При style OFF события нет — это норма, не регресс.
4. При регрессе — rollback по п. «Миграционный фикс».

## Замечания (не блокеры)

- Файл review-migfix.md, заявленный брифом, в репозитории отсутствует (поиск по plans/scratch/git — 0 попаданий). Вердикт «Approved REV-MIGFIX» артефактом не подтверждён; компенсировано независимой проверкой фикса выше (RED→GREEN-история в review-exec-tails.md, воспроизведение тестов). Рекомендовать Orchestrator'у либо создать краткий review-migfix.md по факту этой проверки, либо ссылаться на review-exec-tails.md как на носителя B12.6-вердикта.
- Прежде существовавшие 2 FAIL (w6 expression-preview, glass-tiera lens) — на базовом bf17a972 до лейнов, вне скоупа поезда.
