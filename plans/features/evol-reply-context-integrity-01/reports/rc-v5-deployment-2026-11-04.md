# RC v5 — деплой 2.58.154: привязка и эквивалентность артефакта (PM)

- Дата: 2026-11-04
- Задача: `evol-reply-context-integrity-01` (EVOL-REPLY-CONTEXT-INTEGRITY-01 v5)
- Принятый (отревьюированный) кандидат: `fb761f73731dad6e2b793ff69d4647de37ed8a53` — ветка `rc/accept-fixes`, merge `00a98cae` в `evol/impl`
- Развёрнутый артефакт: `2de11dc0c3a836b44e047484a80ddb0425891ad0` — ветка `release/2.58.154`, версия `2.58.154`
- Прод-база: `e52a06b2` (= merge-base принятого кандидата и деплой-коммита)

## 1. Что проверено локально (PM, на этом рабочем дереве)

1. `git cat-file -t 2de11dc0c3a836b44e047484a80ddb0425891ad0` → `commit`; ветка `release/2.58.154` содержит этот коммит; `config/settings.py` в нём даёт `APP_VERSION = "2.58.154"` (в принятом кандидате — `2.58.153`).
2. `git merge-base fb761f73 2de11dc0` = `e52a06b2`. **Принятый кандидат не является предком деплой-коммита**: релизная линия пересобрана от прод-базы, а не слита из `evol/impl`.
3. Эквивалентность патчей: `git patch-id --stable` совпадает у пар пакета —
   `ff13141d` ↔ `cde7501c` (`24cf2e6d…`) и `fb761f73` ↔ `63a2d2cb` (`064d9cb6…`).
   То есть изменения пакета перенесены на релизную линию как те же патчи (rebase), без переписывания смысла.
4. Побайтовая сверка подсистемы RC v5: **20 из 21 файлов совпадают** (таблица ниже).
   Единственное расхождение — `config/settings.py`, и только в литерале `APP_VERSION`.
5. Релизные коммиты сверх пакета (не меняют поведение продукта):
   `c3cbdafb` — bump `2.58.153 → 2.58.154` (29 файлов: версия в коде/тестах/README/доке);
   `e846d7dc` и `2de11dc0` — переутверждение пинов канона в тестах (`tests/test_asap_w1_semantics.py` и др.), вызванное новой меткой канона.

| Файл подсистемы | blob @`fb761f73` | blob @`2de11dc0` | Итог |
|---|---|---|---|
| `services/canonical_context.py` | `d0afbfe516f7` | `d0afbfe516f7` | совпадает |
| `services/chat_context.py` | `369b76cc5b1e` | `369b76cc5b1e` | совпадает |
| `services/direct_chat_service.py` | `70d156e13a5c` | `70d156e13a5c` | совпадает |
| `services/direct_context_composer.py` | `9843a75e75a5` | `9843a75e75a5` | совпадает |
| `services/direct_l1.py` | `dd6f5277fecb` | `dd6f5277fecb` | совпадает |
| `services/factcheck_service.py` | `109f65583d1d` | `109f65583d1d` | совпадает |
| `services/factcheck_orchestrator.py` | `05f02fa892cb` | `05f02fa892cb` | совпадает |
| `services/factcheck_suitability.py` | `db4cc7a75250` | `db4cc7a75250` | совпадает |
| `services/factcheck_planner.py` | `c76dfb5921d7` | `c76dfb5921d7` | совпадает |
| `services/factcheck_renderer.py` | `9e4c84a93133` | `9e4c84a93133` | совпадает |
| `services/factcheck_context.py` | `fa25bdf619da` | `fa25bdf619da` | совпадает |
| `services/media_marker.py` | `1e8349f79421` | `1e8349f79421` | совпадает |
| `services/media_readiness.py` | `acc9b26ea599` | `acc9b26ea599` | совпадает |
| `services/thread_chain.py` | `3fa2c20338e3` | `3fa2c20338e3` | совпадает |
| `services/tool_router.py` | `3c81b9f81dd2` | `3c81b9f81dd2` | совпадает |
| `services/summary_memory.py` | `607fb11bf539` | `607fb11bf539` | совпадает |
| `services/meme_initiative.py` | `ed2118899653` | `ed2118899653` | совпадает |
| `services/lore_compiler_service.py` | `2db258d871f4` | `2db258d871f4` | совпадает |
| `services/prompt_composer.py` | `b1e224f10f62` | `b1e224f10f62` | совпадает |
| `handlers/factcheck.py` | `dd8a84bd9711` | `dd8a84bd9711` | совпадает |
| `config/settings.py` | `e5af64831714` | `999731bd6170` | отличается |

## 2. Факты деплоя (сообщены DevOps, проверены на сервере; PM их не перепроверял)

- healthz `200` — локально, по SNI и публично; версия `2.58.154`; `NRestarts = 0`; один процесс бота.
- SQLite `user_version = 41`, DDL не выполнялся; медиа-счётчик `66` без изменений.
- Журнал: 0 строк `Traceback`, 0 `ERROR`, 0 `publication_stale`.
- Активация канона подтверждена тремя независимыми источниками:
  заводской отчёт `direct.base.l2_writer` = `fac:44736968bc76(l2-writer-self-correction-rca1)`, `fingerprint=e9dc109330a8`, блоков 112;
  PG `prompt_activations` `id=2916` — `deploy_activate/applied/fac:af56db513733` в `00:55:54 UTC`, активное значение 7328 символов;
  API-каталог согласован с этими значениями.
- Байты живых промптов не изменились: factory `prompts.meme_joke` `2f30ca1f9a6b`, `prompts.meme_image` `f81fe7e4b505`;
  оверрайды владельца в чатах: joke `71303ff62029` / `4bc3425f2f3d`, image `11cf82f45c3a` / `11388ab3a936`.
- Откат не потребовался. Единственное наблюдение: шумные строки `ERROR activation_drift` при старте — вынесено в `plans/backlog.md`.

## 3. Что этот деплой доказывает

- Развёрнутый артефакт существует, поднят, здоров и отвечает; рестартов и падений нет.
- Содержимое пакета RC v5 в развёрнутом артефакте совпадает с принятым кандидатом: все файлы подсистемы побайтово равны,
  кроме литерала версии; патчи пакета на релизной линии те же (patch-id).
- Активация канона L2 Writer выполнена в PG и видна в заводском отчёте и API; живые байты промптов мема не сдвинуты.
- Персистентность и медиа не тронуты: без DDL, без изменения медиа-счётчика.
- `RC-FIN-DEVOPS-PROOF` (M00519) — деплой обычным путём с проверкой по SHA и production-equivalent доказательствами — выполнен.

## 4. Что этот деплой НЕ доказывает

- **Не доказывает живое поведение 23 сценариев NOT PROVEN** (§13.18, §13.21, §13.22, §13.25, §13.27, §13.34, §13.36, §13.37, §13.38, §13.41, §13.42, §13.47, §13.50, §13.51, §13.63, §13.65, §13.87, §13.89, §13.90, §13.102, §13.107, §13.112, §13.119):
  в живых чатах эти пути не наблюдались, а деплой лишь доставил код.
- Не закрывает 115 строк карты вне таблицы сценариев (трасса, инварианты, режимы отказов): у них нет построчного доказательства на кандидате.
- Не подтверждает семантический паритет контекста живьём на каждом LLM/fallback-маршруте (часть DoD).
- **Не подтверждает идентичность «отревьюированный коммит = развёрнутый коммит» на уровне объекта Git**: это разные коммиты одной истории-пересборки.
  Содержимое эквивалентно (п.1), но гейт `--stage release` требует равенства `--candidate == --deployed-commit` и падает на этом различии.
  Устранение: либо узкая пере-приёмка Reviewer на `2de11dc0` (эквивалентность + 3 релизных коммита), либо следующий релиз собирать прямо из принятого кандидата.

## 5. Как это отражено в карте

- `deployed_commit` карты = `2de11dc0c3a836b44e047484a80ddb0425891ad0`; блок `deployment_binding` заполнен этим артефактом.
- Все 147 строк, уже `VERIFIED` на кандидате, получили запись о деплое (`type: deployment`): она подтверждает доставку и живость артефакта,
  но не подменяет наблюдённое поведение — статус этих строк по-прежнему опирается на ревью-доказательства.
- `RC-FIN-DEVOPS-PROOF` → `VERIFIED` (production-доказательство).
- `RC-FIN-DOD` остаётся `PENDING`: DoD конъюнктивен (120 сценариев + живой паритет), деплой его не закрывает.
- 23 сценария NOT PROVEN остаются `PENDING`.

## 6. Прогоны гейта `--stage release` (2026-11-04, этот worktree, `--repo .`)

Все прогоны — на карте с `deployed_commit = 2de11dc0c3a836b44e047484a80ddb0425891ad0` и `candidate_commit = fb761f73731dad6e2b793ff69d4647de37ed8a53`.

### 6.1. Запрошенная форма: `--candidate 2de11dc0 --deployed-commit 2de11dc0` (полные SHA)

По всей карте: `stage=release inventory=312 manual=43 scoped=285 errors=435`, exit 1.
Состав: 148 × «no evidence bound to reviewed candidate» + 148 × «no candidate-bound evidence points to an existing repo artifact»
(все доказательства привязаны к `fb761f73`, не к деплой-коммиту), 137 × «mandatory not ['VERIFIED'] (got PENDING)»,
1 × «candidate mismatch; map candidate_commit must match --candidate», 1 × «RC-FIN-DEVOPS-PROOF: live requirement lacks evidence for stage release».

По срезам (полные SHA): `RC-TARGET-ANCHOR` scoped=41 errors=73 · `RC-MEDIA-OPTIONAL` 27/56 · `RC-EVIDENCE-STATUS` 27/65 ·
`RC-TRACE-ACCEPT` 28/149 · `RC-SPEECH-BOUNDARY` 35/87 · `RC-CONTEXT-FIDELITY` 49/72 · `RC-CONTEXT-CLAIM` 31/49 ·
`RC-DIRECT-SELFCORR` 47/109 — все exit 1.

### 6.2. Отревьюированный кандидат + фактический деплой: `--candidate fb761f73 --deployed-commit 2de11dc0`

По всей карте: `stage=release inventory=312 manual=43 scoped=285 errors=138`, exit 1.
Состав: 137 × «mandatory not ['VERIFIED'] (got PENDING)» + 1 × «deployed commit missing or differs from reviewed candidate».
Ни одной ошибки доказательств и ни одной ошибки артефакта: все 148 `VERIFIED` строк несут запись о деплое с существующим артефактом и совпадающим sha256.

По срезам: `RC-TARGET-ANCHOR` scoped=41 errors=11 · `RC-MEDIA-OPTIONAL` 27/20 · `RC-EVIDENCE-STATUS` 27/29 ·
`RC-TRACE-ACCEPT` 28/138 · `RC-SPEECH-BOUNDARY` 35/39 · `RC-CONTEXT-FIDELITY` 49/28 · `RC-CONTEXT-CLAIM` 31/35 ·
`RC-DIRECT-SELFCORR` 47/63 — все exit 1.
Разница между ошибками среза и числом его `PENDING`-строк — это ошибки зависимостей графа (`required dependency X is not evidenced VERIFIED`).

### 6.3. Вывод по гейту

- Релизного вердикта нет: **exit 1 в обеих формах**. Причина двойная и её нельзя смешивать:
  1. **идентичность** — развёрнутый коммит не равен отревьюированному (см. §1.2 и `open_items.GATE-IDENTITY-RELEASE-LINE`);
  2. **содержание** — 137 обязательных строк остаются `PENDING` (23 сценария NOT PROVEN + строки вне таблицы сценариев).
- Деплой сам по себе не является доказательством поведения: он закрывает `RC-FIN-DEVOPS-PROOF` и деплойную часть DoD, но не 23 сценария и не живой паритет.
- Полный `plan`-гейт после правки: `stage=plan inventory=312 manual=43 scoped=0 errors=0`, exit 0 (структура карты цела).
