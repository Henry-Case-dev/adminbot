# CFG-FINAL F1 — дельта-канарейка CFG-06 на deployed 2.58.104 @ `8ea6ed4e`

Дата: 21.10.2026. Метод: харнес `canary_final.py` (адаптация канарейки
20.10 `cfg06-canary/canary_v2.py`, тот же контур; дельта-добавка —
guard-наблюдения новых швов CFG-07C-G). Артефакты в этой папке, sha —
`SHA256SUMS.txt`.

## Привязка к проду (байт-равенство)

- Runtime-дерево волны F1 **байт-равно** deployed `8ea6ed4e`
  (`../probe-delta.json`: `runtime_delta_8ea6ed4e_to_HEAD_nonplans = []`;
  12 ключевых файлов — sha-совпадение worktree vs `git show 8ea6ed4e`).
- Дельта фактчек-семьи от базы прежней канарейки `7142ffcf` (2.58.99):
  `factcheck_orchestrator.py` +153/−12 (CFG-07C-G egress-guard швы),
  `factcheck_service.py` +23/−2 (07D.5 metatext retry), `settings.py` —
  только bump версии. **Дельта непуста → по плану §1 (ADD-2.6) выполнен
  точечный ре-проб на байтах 8ea6ed4e** (этот прогон), а не ребиндинг.
- Прод-состояние (SSH-проба 21.10, `../ssh/probe-f1-summary.json`):
  `flags.factcheck_pipeline_v2` hot=true, effective=true (bot_settings),
  env UNSET; HEAD `8ea6ed4e`; PID 29475, NRestarts=0 до/после.

## Контур (как в канарейке 20.10)

Единый вход `run_factcheck`; поиск — реальный каскад SearchAggregator
(Tavily ok), LLM — реальная (`deepseek-v4-flash`, apinet.cloud),
Telegram — **МОК** (FakeBot только записывает; ноль обращений к Telegram
API, ноль сообщений в реальные чаты). `db=None` → ветка `legacy_single`.

**Стоимость:** 2 платных прогона v2 (g1+g4; LLM 4 вызова, веб-поиск 4,
primary-fetch 2 — все ok), в пределах бюджета ≤2–3 генераций. Preflight/e4
и W7-композит — бесплатно.

## Вердикты

### g1 (биоспор, Saccharomyces) — PASS
13/13 проверок true (`run-g1.json`): атомизация тезиса, запрос НЕ дословный
слайс с сохранением биномена, реальный поиск (Tavily ok), EvidenceMap с
реальными URL, чанк 2302 ≤4096, HTML, reply-first-only, hrefs строго из
EvidenceMap, `no_service_markers`/`no_admin_tokens`, не-эхо клейма.

### g4 (дата/статистика, 8 млрд) — PASS (с той же честной оговоркой)
14/15: 3 разных интента поиска (вкл. temporal_context), primary-fetch ok,
`publication_date_extracted=False` — дата публикации в разметке страниц не
найдена, **даты не выдуманы** (та же честная деградация, что в канарейке
20.10; соответствует 06E.7). Остальное — true.

### Новые guard-швы (дельта CFG-07C-G) — чистые тексты не тронуты
`guard_observations.count = 0` в обоих платных прогонах: ни одного
срабатывания `public_speech_guard`/egress_guard на честных вердиктах —
контракт «чистое проходит байт-в-байт» подтверждён на реальных прогонах
(`run-g1.json`/`run-g4.json` → `guard_observations`).

### e4 (renderer+delivery, бесплатно) — PASS 4/4 варианта
`run-e4.json`: длинный 6358+ симв с URL/Unicode → чанки ≤4096 с балансом
тегов; пустой evidence → честное ограничение без фальшивых ссылок;
HTML-инъекции → экранирование, живых script/href вне whitelist нет;
TelegramBadRequest → ровно сломанный чанк деградирует в plain.

### Диспут-E2E и композит S1–S8 (06J.6/06.B) — PASS
`probe-dispute-w7.txt`: `tests/test_factcheck_w7_acceptance_cfg06.py` —
**8 passed** на тех же deployed-байтах (S1–S8, включая S6: спор 260 без
reply-chain → предмет из хронологии, тезис проверен, автор сохранён; S7:
fallback — тот же контракт). Фокус-регресс всего фактчек-семьи —
`../regression-focused.txt` (535 passed, EXIT 0).

## Ограничения (честно)

- Envelope-ветка (приватная БД чата) в тестовом контуре отсутствует — как
  и в канарейке 20.10; её контракты фризятся тестами W3/W6/W7.
- Живые осмотры в реальных чатах не проводились (запрещены владельцем);
  техническая живая часть = прогоны на deployed-байтах с реальными
  поиском/LLM и моком Telegram.
- G.4: публикационная дата не извлечена — механизм попытки доказан, даты
  не выдуманы (06E.7).
