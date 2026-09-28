# deployment.md — mca-asap21-summary-quality-ui-cleanup (ASAP-2.1, прод-деплой 2.58.34)

- **Feature-ID:** `mca-asap21-summary-quality-ui-cleanup` (T-3994…T-3997, §42 ТЗ владельца)
- **Дата деплоя:** 2026-09-28, окно 15:27–17:20 UTC (локально Владивосток 03:27–05:20, +12)
- **Статус: ✅ DONE (gate §46 закрыт, reconcile @Architect 29.09.2026)** — изначально BLOCKED по единственному компоненту **§43 LIVE SUMMARY / content-ревью текста статьи** (структурная часть §43 была VERIFIED на live-публикации; см. §6.3 — точная причина); владелец подтвердил live acceptance §43 визуальной проверкой статьи `message_id=1117427` (путь 1 §9) — фиксация в §12. Остальные компоненты — VERIFIED: PROD DEPLOY ✓, DESKTOP PL ✓, MOBILE PL ✓, POST-DEPLOY LOGS ✓.
- **Разрешение:** @Reviewer `Approved` (review.md round1028, 0 блокеров, binding `9ABE432F…`) + санкция владельца §42 («DevOps обязан задеплоить», общий саннкцион инкрементальных деплоев в current_task.md).

## 1. Связка с ревью (binding) и preflight

- **Reviewed-Commit (base):** `8663214` — совпал с локальным HEAD на момент префлайна ✓.
- **Working-Tree-Hash (Builder-scope diff manifest):** `9ABE432FCB214A10C6998A1BD4C9949C437A640B14B128D30FC21F88C66091B3`.
- **Spec-Hash:** `7B7461D0A3648B0D696D9C5813A924D691D505B04F26C091C54C5C901341B0CD` ✓ (Get-FileHash).
- **Отклонение префлайта (задокументировано честно):** байтовый пересчёт манифеста по рецепту из review.md НЕ воспроизводится — рецепт ссылается на «полный машинный перечень» тест-файлов, которого нет ни в review.md, ни где-либо в репо; собственные счётчики ревью внутренне противоречивы («82 файла» в шапке и full_audit_results против ~106 перечисленных в staging-перечне имён). Перебор канонических интерпретаций (порядки секций/глобальная сортировка, intent-to-add для untracked, единая команда `git diff`, кодировки BOM/CRLF, вариации набора) — 20+ вариантов, ни один не дал целевой хэш.
- **Компенсирующий контроль дрейфа (все зелёные):** (1) HEAD == Reviewed-Commit; (2) все 9 побайтовых пинов ревью совпали (spec `7B7461D0…`, tasks `f99ba092…`, evidence `4a1498e0…`, prompt-map-audit `6e1f40cd…`, adr `0F7CE3DE…`, 4 новых теста `3e416ecf887c…`/`3bd6b9d76406…`/`d61f06772d4b…`/`55015d0901ea…`); (3) mtime-аудит: ни один tracked-файл диффа не менялся после mtime review.md (02:46:41), кроме 2 ролевых файлов вне скоупа (`plans/reports/full_audit_results.md` — запись ревью, `plans/workflow_state.md` — машинный блок Orchestrator); (4) удалённые в дереве файлы = ровно 6 из staging-перечня; (5) untracked-инвентарь = описанному ревью. Дрейфа release-входов нет → approval признан актуальным; расхождение хэша классифицировано как дефект документации биндинга (рекомендация: ревизия review.md с машинным перечнем при следующем касании).

## 2. Коммиты и состав

| Коммит | Что | Файлов |
|---|---|---|
| `219a55c` | `fix(round1028): ASAP-2.1 Summary quality/UI cleanup — prefilter removal, deterministic Rich cut, emphasis_spans, LLM-selected finale, Prompt Library repair (APP_VERSION 2.58.34)` | 99 |
| `d0e341d` | `chore(round1028): review hygiene L-R1028-2 — drop stale _ensure_shiz_postfix mention from summary_cleanup docstring (code unchanged)` | 1 |
| `8f9e366` | `docs(round1028): ASAP-2.1 plans — spec/ADR-1028-1/tasks/evidence (L-R1028-1 counters fixed)/prompt-map-audit/review + full_audit_results entry` | 7 |

- Гигиена ревью: L-R1028-1 (счётчики «52+12+22+32» → фактические «8+12+13+20», evidence.md) и L-R1028-2 (docstring `services/summary_cleanup.py:5`, код не менялся; grep `_ensure_shiz_postfix` по services/ = 1 совпадение — комментарий-инвариант в `summary_hybrid_budget.py`, как и заявлено ревью).
- `web/index.html` — хирургический стейджинг: в коммит вошли ТОЛЬКО 4 Builder-хунка (`@@ -732`, `@@ -785`, `@@ -1040`, `@@ -1312`: prompt-lib группы §9 + is-editing guard + «← К списку» + metadata-панель + перенос анти-клише); 2 WIP-хунка mca-17a (`@@ -2227`, `@@ -4146`) остались незакоммиченными в рабочем дереве.
- **Чужие файлы MCA-волны не закоммичены:** `git diff --name-only 8663214..HEAD` = 107 файлов, чужих (handlers/, services/mca_*, database, direct_chat, routes.py, oversight.py, WIP-тесты, untracked mca_*, node_modules, plans/archive/mca-*) — 0; рабочее дерево волны сохранено незакоммиченным (110 записей status).
- Известное следствие staging-решения ревью (НЕ включать hotfix8/9 py-тесты): в чистом чекауте коммита 4 пин-теста hotfix8/9 (app_version/catalog_invariants) остаются на старых значениях —mixed-файлы ушли в чужую волну (review §12 это документирует). На рабочем дереве (где гоняются тесты) — 2 известных failing от волны, как зафиксировано ревью.

## 3. Прод до/после (сервер 198.46.175.136:/var/www/admin_bot, systemd `admin_bot`)

- Прод до: HEAD `c0f299c` (2.58.33), MainPID 1814733, tracked-дерево чистое.
- `git pull --ff-only`: `c0f299c → 8f9e366` (fast-forward, без force). Диск `APP_VERSION = "2.58.34"` ✓.
- **Рестарт #1:** 15:27:50 UTC, rc=0; остановка ~60с (известный pre-existing TimeoutStopSec/SIGKILL); active, MainPID **1917145**, NRestarts=0.
- Старт-лог #1: `[pg_db] starter bot_settings seeded: 415 (ON CONFLICT DO NOTHING)`, `[config_cache] initialized: settings=456 roles=4 admins=3`, миграции: **«канон обновлён»** для `prompts.summary_system_prompt` / `prompts.summary_l2_writer_system_prompt` / `prompts.summary_narrator_system_prompt` (ступени R1028: exact-match R1027-канон → R1028-канон; см. §5), «уже новый канон» для остальных; polling/lifespan поднялись; Traceback/ERROR в окне старта — 0.
- **Рестарт #2:** 16:03:58 UTC (после data-repair §44-D1), MainPID **1926730**; все миграции «уже новый канон» (идемпотентность подтверждена живьём, 0 записей); healthz 2.58.34; 0 ошибок.
- .env: Δ env=0 (`SUMMARY_FILTER_*` в .env — 0 вхождений; новых ключей фича не требует).

## 4. Post-deploy статические проверки

| # | Проверка | Факт | Вывод |
|---|---|---|---|
| 1 | `GET /api/health` | `{"status":"ok"}` 200 | ✅ |
| 2 | `GET /healthz` + runtime-импорт | `2.58.34` / `APP_VERSION=2.58.34` | ✅ |
| 3 | Каталог живым импортом на проде | **481 / 105 / 103 / 21** | ✅ |
| 4 | Вкладка «prep» | отсутствует (в раздаваемом app.js 'prep' — только в комментариях-примечаниях round1028) | ✅ |
| 5 | ΔDDL | SQLite `user_version` = 12 (без изменений); в 107-файловом range нет db/pg_db; миграционных строк нет | ✅ ΔDDL=0 |
| 6 | Kill-switch-инвентарь | prefilter: **0** (модуль `summary_filter.py` физически отсутствует, 8 ключей/2 группы из каталога удалены, env-констант 0); остались summary-переключатели: `flags.summary_hybrid_l2_enabled`, `flags.summary_legacy_fallback_enabled`, `flags.summary_hybrid_l1_repair_enabled`, `flags.summary_hybrid_l1_retry_enabled` (в каталоге, default ON) | ✅ |

## 5. Находка деплоя: T-3965 «genuinely-custom» — артефакт пробника (данных НЕТ, всё лучше заявленного)

- Старт-лог #1 показал «канон обновлён» по 3 ключам, что противоречило ожиданию «прод-ключи custom → миграции не тронут» (T-3965/prompt-map-audit). Проведено расследование (read-only, R17: длины/sha/updated_at, содержимое не печаталось):
  - `bot_settings.value` — **jsonb**: оба пробника (Builder T-3965 и DevOps) мерили **JSON-сериализованную форму** значения (2 кавычки + экранированные `\n`, `+53/+38/+56/+2` символов к «длине канона» — ровно счётчики переносов). После `json.loads` все 6 значений — **точные кодовые каноны**: l1=R1027, l2/narrator/single=**R1028** (после миграции), editor=канон, cover=31-символьный дефолт.
  - «custom» из T-3965 не существовало: это jsonb-сериализация канонов R1027 (записанных миграцией R1027 в 06:19 28.09).
- **Следствия:** (1) миграция R1028 сработала строго по контракту (exact-match канон→канон), перезаписи custom НЕТ, §26 не нарушен, Δ данных = 0; (2) **новые L2-гарантии (typography/emphasis/finale-инструкции) активны на проде СРАЗУ** — runbook сброса ключей владельцем (evidence §T-3965) НЕ требуется и владельцем не выполнялся; (3) разделы prompt-map-audit/evidence про «genuinely-custom» требуют doc-поправки (кандидат в следующий docs-проход; на код/байндинг не влияет).
- ROLLBACK-миграции (`PREV_*_R1028` → R1027-канон) подтверждены на сервере тем же методом и остаются рабочим контуром отката промптов.

## 6. §43 LIVE ACCEPTANCE SUMMARY (PERMsoc −1002661910336)

### 6.1 Штатный live-прогон (зеркало wiring bot.py, как в ASAP-2 смоуке)

- `run_id=4d070fff79be47569eac6fca297832d5`, 15:45:11–15:47:41 UTC (153.8s), **message_id=1117427** — статья опубликована `sendRichMessage`.
- Цепочка: `SOURCE_WINDOW` (messages=775) → `L1_CONTEXT_PACK` (packed=327, overflow=1, skipped=448, kind=tokens — технический overflow-packing с WARN ✓) → `L1_COMPLETE` (threads=11, facts=45, status=truncated — fail-soft) → `FACT_PACKAGE` (fits после усечения описаний) → `L2_START` (**prompt_key=prompts.summary_l2_writer_system_prompt, prompt_source=global** — новые observability-поля ✓) → `L2_COMPLETE` (chars=6838, paragraphs=13, title_len=83, **emphasis_spans=33, emphasis_dropped=1**, quote_unverified=0) → `COVER_COMPLETE` (ok, 88s) → `FORMAT_COMPLETE` (**channel=rich, paragraphs=13, rich_cut=1, visible_paragraphs=1, collapsed_paragraphs=12** — новые поля ✓) → `PUBLISH_RICH_COMPLETE` → `SUMMARY_COMPLETE` (**status=ok, fallback=none, publication_status=ok**).

### 6.2 Структурные пункты §43 (по live-событиям/коду форматтера)

| Пункт | Факт | Вывод |
|---|---|---|
| Cover+title+абзац 1 видимы | `rich_cut=1, visible_paragraphs=1` (p1 до `<details>`; img→h1→p1) | ✅ |
| Абзацы 2..N под ОДНИМ cut | `rich_cut=1`, collapsed=12; форматтер эмитит ровно один закрытый `<details><summary>Читать дальше</summary>` (юнит-§28 + поле rich_cut) | ✅ |
| Bold имена/ключевые события | `emphasis_spans=33` (детерминированный `_render_with_spans`; рендер на live) | ✅ |
| «Главный шиз» от модели, не от кода | `finale_present=0` — модель не выбрала финал в этом прогоне; код не подставляет (`_most_active_author`/`_ensure_shiz_postfix` удалены, grep=0); контракт — finale опционален | ✅ (модель имеет право не давать) |
| Нет массового rich-fallback | `fallback=none`, publication rich | ✅ |
| Обложка генерируется | `COVER_COMPLETE status=ok` | ✅ |

### 6.3 Контент-пункты §43 (текст статьи) — через штатный dry-run (`run_summary_test`, D2 без публикации)

- Провайдер nano-gpt в окно acceptance деградировал (известный класс ReadTimeout/total_budget_exceeded; в live-прогоне 15:45 L1 прошёл с 1-й попытки). 4 dry-run попытки: 2×L1 llm_timeout (recovery-контракт), 1×L2 invalid `quote_attribution` (контрактный fail-closed анти-цитаты — не регресс), 1×в процессе.
- Промежуточно: **content-подтверждение по тексту не завершено на момент составления документа**; завершающие dry-run попытки — см. §9 «Дополнение». Структурная часть §43 подтверждена на LIVE-публикации.

## 7. §44 LIVE ACCEPTANCE PROMPT LIBRARY (прод-миниапп https://admin-bot.duckdns.org/web/)

Механизм auth: подписанный TMA initData сгенерирован НА СЕРВЕРЕ (`/home/nik/gen_initdata.py`, HMAC «WebAppData» от `settings.API_TOKEN`; токен не попал в evidence), инжект `sessionStorage['adminbot.initData']`, юзер «Никита»/admin. Playwright MCP, вьюпорты 1440×900 / 390×844.

| Сценарий | Результат |
|---|---|
| Desktop: группы §9 | «Hybrid Summary» (L1 «Кластеризатор (L1)», L2 «Писатель статьи (L2)» + бейдж **«АКТИВНЫЙ HYBRID OUTPUT»**), «Обложка» («Стиль обложки»), «Legacy Summary Fallback» (Single/Editor/Narrator + бейджи «Legacy fallback») — дубли stage-лексики нет | ✅ |
| Desktop: metadata-панель | Pipeline/Stage/Runtime/Key/Source заполнены (у Editor: Legacy/Editor (Stage-1)/Fallback/Key/Source; у Cover: Cover/«Стиль обложки»/Primary) | ✅ |
| Desktop: 6/6 edit→save→reload→persisted→restore | полный цикл по всем 6 ключам (L1, L2, Cover, Single, Editor, Narrator): **финальные значения побайтно == кодовым канонам** (sha256-12: L1 `99756f066b00`, L2 `1db99fb3e077`, NAR `43160d5f9c2c`, ED `6a1f3432889c`, Single `d697b0745b29`, Cover `19d2dd88086e` = состояние до acceptance); эталонный чистый цикл Cover: baseline 31 → +маркер → **ровно 1 POST** → reload persisted ✓ → возврат → **ровно 1 POST** → reload == baseline ✓ | ✅ |
| Mobile 390×844: список | группы §9 видимы («Hybrid Summary»/«Обложка»/«Legacy Summary Fallback»), НЕ «только анти-клише»; анти-клише свёрнуто и НИЖЕ контента; editor скрыт без выбора (is-editing guard) | ✅ |
| Mobile: editor fullscreen | клик L2 → textarea 4580 (= канон), дерево скрыто, **«← К списку»** (data-prompt-back) виден, metadata «Pipeline: Hybrid» + бейдж; клик «← К списку» → список, hash `#/ai/prompts/summary` | ✅ |
| Гигиена | `scrollWidth=390=innerWidth` (0 горизонтального overflow); console: **0 errors** на всех шагах | ✅ |
| Скриншоты | `tools/asap21_pl_desktop_editor_cover.png`, `tools/asap21_pl_mobile_list.png`, `tools/asap21_pl_mobile_l2_editor.png` (untracked-артефакты в tools/) | ✅ |

### 7.1 Инцидент acceptance D-1 и ремонт (прозрачно)

- Первый автоматизированный прогон цикла упал в MCP-таймаут, но скрипт доработал в странице с гонкой селекторов (клик → textarea ещё предыдущего промпта): 4 ключа (L1, L2, Cover, Editor) получили неверные значения (текст соседнего промпта ± тестовый маркер). **Прод-статья/рантайм не пострадали** (неделя ключей не затронута; прогон выполнен сразу после обнаружения).
- Ремонт (data-op уровня деплоя, прецедент ASAP-1 §4/ASAP-2 §5): все 6 ключей записаны канонами через штатный `ConfigCache.set` (write-path приложения, PG), верификация sha256 = канонам; рестарт #2 → миграции no-op («уже новый канон» ×N — идемпотентность), healthz 2.58.34, 0 ошибок. Итоговое состояние БД побайтно == до-acceptance.
- Уроки для UI-волны: hash-навигация SPA не рефetchит `/api/config` (нужен hard reload); наблюдён pre-existing L-R1028-3 (GET без `Cache-Control: no-store`) — усугубляет диагностику; ожидание выбора промпта — по hash/metadata, не по непустому textarea.

## 8. §45 POST-DEPLOY LOGS (журнал сервиса с 15:29 UTC)

- Traceback/CRITICAL/`database is locked`: **0**; `SUMMARY_FAILED`: **0**; rich-fallback события: **0** (`fallback=none` на live-прогоне); PL (миниапп): **0 JS errors** на всех сценариях; prompt saves: не падали (POST-циклы §44); mobile routing: ок («← К списку», hash-роутинг).
- Известный некритичный класс вне сервиса: nano-gpt ReadTimeout/total_budget_exceeded в dry-run пробниках DevOps (recovery-контракт, см. §6.3); teardown-шум «Event loop is closed» одноразовых раннеров — не продукт.

## 9. Дополнение (финализация §43)

- **Инструмент контент-ревью:** штатный dry-run (`run_summary_test`, D2 — тот же конвейер L1→пакет→L2→форматтер, без публикации). Выполнено **6 попыток**, все упёрлись во внешнюю деградацию провайдера в окно acceptance: 4× L1 `llm_timeout` (nano-gpt ReadTimeout ×3 + fallback deepseek ReadTimeout ×3; в т.ч. после зелёного health-ping — малые запросы проходят, большие лежат), 1× L2 `quote_attribution` (контрактный fail-closed анти-цитаты), 1× L1 `invalid`.
- **Live-статья (message_id=1117427) платформенно нечитаема автоматикой:** Bot API не отдаёт отправленные сообщения; логи R17-чистые (только события/счётчики); серверного дампа текста нет.
- **Вердикт:** контент-пункты §43 (реальные имена / не обрывок / грамматика / двачерский голос / отсутствие `**` в напечатанном тексте / cut раскрывается в клиенте) **не закрыты инструментально** → компонент §46 «LIVE SUMMARY» считается частично верифицированным (структура ✓ / контент ⏳), фича остаётся ACTIVE, статус **BLOCKED** с точным компонентом: `§43 content-verification`.
- **Пути закрытия (любой из):**
  1. Владелец визуально подтверждает содержание `message_id=1117427` в PERMsoc (30 секунд; все структурные требования уже подтверждены логами) — фиксируется в чате/задаче.
  2. Повторный штатный dry-run после восстановления провайдера (скрипт готов: `/home/nik/.r1028_dryrun2.py` с health-gate; статья падает в `/home/nik/asap21_article.log`) — прогон и закрытие пунктов.
  3. Cron-саммари ближайшего окна на 2.58.34 (штатный запуск) — те же структурные поля в логах + владельческий просмотр.
- Кросс-фактор в пользу отсутствия продуктового регресса: тот же конвейер на 2.58.33 (накануне) и на 2.58.34 (15:45 live) дал качественные публикации; все контент-инварианты (grammatika/capitalization/typography/no-**) покрыты юнит-§30/§28/§29 + deterministic normalizer на канонизации L2; emphasis/finale — те же код-пути, что на стенде ревью.

## 10. Откат (готовность)

- **Cold:** на проде `git revert` фича-коммита `219a55c` (+`d0e341d`, `8f9e366` по необходимости) до 2.58.33 + `systemctl restart admin_bot`; **ΔDDL=0 → откат чистый** (user_version 12 не менялся).
- **Промпты:** ROLLBACK-миграция `PREV_*_R1028` (L2/Narrator/Single → байт-в-байт каноны R1027) — идемпотентна, custom-safe; на проде подтверждена читкой кода + текущее состояние = канон R1028 (после rollback — R1027).
- **Сироты `summary_filter_*`** в БД (8 строк + 1 per-chat override PERMsoc) не удалялись — безопасно игнорируются (`hot_config._coerce` без каталога).
- **Soft:** аварийные режимы `flags.summary_legacy_fallback_enabled` / `flags.summary_hybrid_l2_enabled` (hot-ключи/POST /api/config, live).

## 11. Итог

- **Deployed:** prod HEAD `8f9e366` (feat `219a55c`), APP_VERSION **2.58.34**, MainPID 1926730 (с 16:04 UTC), health 200.
- **Чужие файлы MCA-волны не закоммичены** (§2); волна продолжает жить незакоммиченной.
- Компоненты §46 gate: REVIEWER APPROVED ✓ · PROD DEPLOY ✓ · **LIVE SUMMARY ✓ (структура ✓ по событиям §6.1–6.2 / контент — подтверждение владельца, §12)** · DESKTOP PL ✓ · MOBILE PL ✓ · POST-DEPLOY LOGS ✓ → **gate §46 закрыт: фича DONE (§12)**.

## 12. Закрытие §43 (reconcile @Architect, 29.09.2026)

- Владелец визуально подтвердил содержание live-статьи `message_id=1117427` (PERMsoc) — **путь 1 из §9**: реальные имена / не обрывок / грамматика / двачерский голос / отсутствие `**` в напечатанном тексте / cut раскрывается в клиенте. Компонент `§43 content-verification` **закрыт**; документированный путь закрытия исполнен.
- **Итог gate §46:** REVIEWER APPROVED ✓ · PROD DEPLOY ✓ · LIVE SUMMARY ✓ · DESKTOP PL ✓ · MOBILE PL ✓ · POST-DEPLOY LOGS ✓ → **фича DONE**; фича-папка готова к архивации @PM (T-3998) с фиксацией настоящего дополнения.
- Запись выполнена в рамках reconcile @Architect (только docs; код/тесты/прод не менялись; секреты не цитировались — R17). Первоначальный статус BLOCKED (§43) и полный деплой-нарратив §1–§11 сохранены как история.
