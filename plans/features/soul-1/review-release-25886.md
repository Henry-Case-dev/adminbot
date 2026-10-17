# SOUL-1 — REV-REL-SOUL: независимое ревью релиза 2.58.86 (18.10.2026)

**Вердикт: Needs Fixes** — узкий и исполнимый. Дельта/изоляция, preflight, капчуры (ii)/F2/F4, включение и авто-откат подтверждены независимо (ниже §1–§4, §6); НО: (1) в деплое — активный дефект пути «Стиль письма: сохранить глобально» (диагноз подтверждён по коду; фикс `68cd05b2` уже в master, ждёт мини-релиза); (2) F5-скан закрыт лишь на 10/50 traits; (3) docs-правки отчёта (кодировка, хеш бэкапа); (4) деплой-скрипт `F3_migration_wait` матчит устаревшую строку журнала; (5) W6-фикстура устарела (диагноз верен, нужен evidence-проход). Dropdown — отдельная WG-задача (атрибуция: регрессия внесена WG-релизом). Остальное — VERIFIED.

## Привязка

| Поле | Значение |
|---|---|
| deployed runtime | **`eafbe2e7`** (`release/soul1-2.58.86`; healthz `2.58.86` ×3) |
| tip ветки (отчёт+evidence) | `d5191450` (запушен: `ls-remote` = tip) |
| прод-предшественник | `95526863` (win-glass 2.58.85) |
| Runtime-эквивалентность | `git diff 72b91d6e d5191450 -- services` = пусто; `-- web` vs `0ca661fe` = пусто; после `eafbe2e7` коммиты не трогали services/web/config/tests/tools (docs-only) |
| Мои прогоны | worktree `rev-rel-soul` @ `d5191450` (services==eafbe2e7); живой прод не читал — все live-факты проверены по evidence |

## 1. Дельта/изоляция — VERIFIED (мои git-пересчёты)

- `git diff --name-only 95526863 eafbe2e7` = **628 файлов**; `delta-vs-base.txt` содержит те же 628 (631 строка − 3 заголовка). Классификация: soul1-runtime 59, soul1-tests 76, bump 31, docs+docs-plans 462 → 628; **UNCLASSIFIED=0**.
- Состав: services == `72b91d6e` (F1/F3-фикс), web == `0ca661fe`; config/tests/tools отличаются только version-пинами (bump-commit `e0756310` = 31 файл; `eafbe2e7` = runbook-sync).
- WG-артефакты byte-equal проду и master (6 путей; `git diff 95526863 d5191450 -- <путь>` пусто). Мои sha256_12 совпали с deploy-run D1 **12/12**: fullscreen-policy `96db06425079`, glass-refraction `6a09d962d59d`, glass-probe `b2e6a1f987c6`, index.html `0971d49d5337`, app.js `5a810c0f4443`, app.css `3c67a414da7b`, prompt_registry `a606bcafc1be`, smartmodule_phrases `04ed64429e88`, prompt_composer `fd8a2a70d5d7`, speech.py `a69a67536ebe`, initiative_vitality `4dd2510532bd`, settings.py `d61cb7a4e3f6`.
- CFG отсутствует (`git ls-tree` пусто). Секрет-скан: 22 сработки — синтетические тестовые дубли (`sk-SYNTHETIC-*`, `123456:TEST_TOKEN*`, R17-строки); реальных секретов нет.
- Ниточка: в `wg-byte-equal.txt` для WG-файлов даны 12-префиксы **blob SHA-1** (`81ab76301968`), а в D1-проверке — sha256 контента; оба вида сходятся с git, но стоит помечать, какой хэш где.

## 2. Preflight — VERIFIED (мой повтор в релизном worktree)

- registry `--check` → **575 == REGISTRY** OK; parity **13**; `test_soul1_*.py` (30 файлов) **599**; смежные 70; периметр (селектор лейна) **3917 passed / 0 failed / 10244 deselected** (мой прогон 149.5s); node `tests/js` **87/87**; W7-инструмент **5/5, 88 проверок** (мой повтор через venv).
- **W6-фикстура — диагноз подтверждён моими прогонами:** на закоммиченной фикстуре RED (`TimeoutError … .speech-section hidden`); после подстановки пере-снятой (`fixture-regenerated-by-dump-script.json`, файл затем возвращён `git checkout --`) — **failures=0, POST=16, shots=94**. Структурно: stale `examples.status=not_implemented_w4`, нет `starter/telemetry/policy`, шаблон читает `starter.expected`/`telemetry.approved`/`policy.*` → TypeError в render. Фикстура релизом не менялась (== master).
- **W2-SHELL — предсуществование на базе подтверждено:** идентичная сигнатура на `95526863` (тот же локатор `.oversight-mobile-option`, перехватчик `card glass-panel p-4 col-span-full`; скриншоты ветки и базы идентичны).
- Frozen-check (адаптер): OK — якоря/ассеты/LF/WG-маркеры сохранены. FS-матрица 12/12 и embedding-sweep 534 — переиспользованы из логов лейна (объём соразмерен, не перепрогонял).

## 3. Капчуры (ii)/F5/F2/F4

- **(ii) — CLOSED (согласен):** `summary_editor` `6a1f3432889c`/2023 (базовые и расширенные маркеры 0; контент «СИСТЕМНАЯ РОЛЬ: Ты — редактор саммари…»), per-chat `summary_cover_style` `35013bd88081`/110 (0/0; «Comic-book style…») — снято живым чтением, sha совпали с ожиданием R2, вердикт дан.
- **F5 — ЧАСТИЧНО:** `personas` (2 ряда) — все поля пустые (name/biography/system_prompt_overrides) → главный вектор конфликта «Характер: {overrides}» отсутствует ✓. Но маркер-скан `persona_traits` покрыл только **10/50** строк (в capture-скрипте `tr[:10]`; строка «omitted=40 (no markers in first 10)»), а отчёт формулирует «50 строк, маркеров 0». Нужно: досчитать остальные 40 read-only (одна выборка) либо скорректировать формулировку отчёта.
- **F2 — VERIFIED:** `SMART_VERBALIZER_MODES_ENABLED` в `.env` отсутствует → код-дефолт `True` (`config/settings.py:568`) ⇒ «≠0» выполнено; code-fallback принят ранее (R2, OFF-паритет W2). Процесс-environ не читается (PermissionError) — ожидаемо.
- **F4 (отклонение) — ПРИЕМЛЕМО/ДОКУМЕНТИРОВАНО:** env `NOSTALGIA_ENABLED` отсутствует, но PG `memory.nostalgia_enabled=true` — pre-existing с 2026-09-06 (релизом не создан/не изменён); воркер поднят (лог 21:55:11); кандидат идёт через Core+жанровую рамку (AMD.2.6), лимиты (max_per_day=3). Факт зафиксирован честно; действий не требуется (владелец может отключить — не блокер).

## 4. Включение — VERIFIED

- Порядок: PG (21:54:45) + `.env` → **один** graceful-рестарт (21:54:51) → healthz `2.58.86` (24 s); после deploy-рестарта и до enable оси OFF (`FLAGS_COUNT=0`).
- gates **10/10 ON**; blocks 89; `withheld=11` (список совпал с 11 ключами класса удержания); WARNING `persisted speech value withheld` (13 строк); журнал 0 ERROR/CRITICAL; `NRestarts=0`, `ExecMainStatus=0`.
- `character.core`: создан штатным API (не SQL) → `act:040581a3b4b0` / `r1.040581a3b4b0`, 2835 зн., `owner_edit`, `source=global`, `level=full`, `differs_from_factory=false`.
- try-проба: `layers_current=[channel_contract, channel_contract, core]`; `versions.core=r1.040581a3b4b0`; `conflicts=[]`; инициатива `POST /api/config` → 200 (hot).
- **`style.policy` отсутствует** — следствие дефекта §5 (поведенчески = пустая заводская политика).
- SQLite: `backup-guard done in 153.0s` → v36 applied 0.1s → `user_version=36`, таблица `humor_samples`, книга миграций.

## 5. Дефект follow-up №1 — CONFIRMED (диагноз и объём); фикс уже в master

- `services/style_policy.py:2275` — `target.set(...)` без `await` в ветке `scope=global`; `ConfigCache.set` — async (`services/config_cache.py:681`); чат-ветка использует `await set_root(...)`. Последствие: корутина выбрасывается → `RuntimeWarning`, `applied=true`, PG не обновляется (`source=default`, `global_present=false`).
- Объём: **единственный** такой вызов — grep по services/web всех cache `.set(`: остальные с `await` (sync-кэш в проде не используется).
- Фикс: на master `68cd05b2` (+71/−1: `await` + коммент + регресс-тест `_StrictAsyncCache`, `TEST-LIFECYCLE: REGRESSION`); мой прогон `tests/test_soul1_style_policy.py` = **61 passed** (тест включён). Прод-подтверждение — только после деплоя.
- Классификация «current-blocker для пути “Сохранить глобальные правила стиля”» — согласен: пункт «Speech Style Policy через MiniApp меняет генерацию» для scope=global FAILED (chat-scope работает).

## 6. Первая попытка деплоя — VERIFIED (авто-откат); + ниточка деплой-скрипта

- health-miss 21:47:35 (VACUUM INTO 153 s > 90 s окно) → авто-откат 21:47:48 → база жива 21:48:10 (`2.58.85`); 0 ERROR в окне; следов включения нет (`HEAD=95526863`, `ENV_AXES=0`, PG-ключи SOUL отсутствуют, документы не создавались, `user_version` остался 35); второй прогон успешен.
- **Ниточка:** шаг `F3_migration_wait` во втором прогоне отработал за 2.2 s и вывел **устаревшие** строки журнала (21:46/21:48 от первой попытки/отката), а не завершение текущей миграции (21:54:26); фактическую защиту дало 5-минутное health-окно (F4 188.4 s). Рекомендация: матчить строки после времени рестарта или проверять `user_version==36` перед health-шагом (иначе следующая долгая миграция снова упрётся в health-miss — безопасно, авто-откат, но релиз не сядет).

## 7. Dropdown «Аналитики» (инцидентный, вне SOUL) — атрибуция

- По имеющемуся evidence: **регрессия внесена релизом WIN-GLASS-P0 2.58.85** (не «предсуществующее»):
  - тот же инструмент (`ui_asap8_w2_shell_e2e.py`, sha `0b67e8d63e7d`) на линии 2.58.84 давал `W2-SHELL-E2E-OK, failed_checks={}` (инструмент включает U02-клики `.oversight-mobile-option`); на 2.58.85/2.58.86 — RED с одинаковой сигнатурой;
  - механизм задокументирован в `review-wg.md`: слой рефракции при включении ставит hosts инлайновые `overflow/isolation/position`, при выключении снимает; в 2.58.84 модуля не было;
  - process-gap: WG-релиз **не прогонял** U01/U02 shell-e2e (в его preflight — refraction-e2e 37/37, fs-matrix и др.), поэтому регрессия ушла в прод.
- Чего не хватает: (а) каузальный toggle (`?glassrefract=off`/выключенный tier → тап работает; какая именно inline-проперти виновата); (б) подтверждение на реальном Telegram WebView (owner); (в) фикс + повтор shell-e2e + визуальная приёмка — лейн DROPDOWN-WG.

## 8. Прочие findings (docs/evidence) — обязательные к правке

1. **Отчёт `release-2.58.86-report.md` в репо — моджибейк:** 136/238 строк (двойное UTF-8→cp1251; чистые только последние ~47 строк) + дублирующий заголовок «## 7. Девиации». Правка: пере-записать отчёт в UTF-8 + убрать дубль.
2. **Хеш PG-бэкапа в отчёте неверный:** `253b548e650c1c2d` не встречается ни в evidence, ни в репо; фактически `5cc7de90e9132d05` (`~/soul86_pg_backup_20261017T215121Z.json`, 117227 B; совпадает в capture-before/deploy-run/final-verification). Правка: заменить в отчёте.
3. **F5 10/50** (см. §3) — досчитать остальные 40 read-only.
4. **W6-фикстура** (см. §2) — пере-снять штатным генератором отдельным W6-evidence проходом.
5. **Деплой-скрипт `F3`** (см. §6) — hardenить матчинг журнала.
6. Ниточки: `deploy-run.txt` содержит искажённые cp1251-фрагменты кириллицы в секции E_capture (канонический `capture-before.txt` чист); хвосты логов обрываются на `[sudo] password for nik:` (безвредно, но читаемость).

## 9. Решения

- **(а) Мини-релиз 2.58.87 для follow-up №1 — ДА.** Состав: фикс `68cd05b2` (с его собственным ревью) + bump 2.58.87 + focused на релизном дереве (style_policy/soul1/parity/registry) + деплой тем же скриптом (по возможности с фиксом F3) + пост-проверка: после «Сохранить глобально» в «Стиле письма» появляется `style.policy` в PG, `GET /api/speech/style` → `global_present=true`, ревизия растёт; в try-пробе появляется `style_policy_hint` при непустых правилах. Rollback-план не меняется.
- **(б) Dropdown — отдельная задача** (DROPDOWN-WG: каузальная изоляция → минимальный фикс stacking → shell-e2e GREEN → мобильная визуальная приёмка). Бандлинг в 2.58.87 — только если к вырезке фикс пройдёт своё ревью и e2e; иначе следующий мини-релиз. Дедлайн style-фикса из-за dropdown не сдвигать.
- **(в) 29 READY_FOR_LIVE (20 + 9 по двум картам; мой пересчёт):** (1) DevOps/PM: re-anchor `candidate/deployed` на `eafbe2e7` + release-стадия гейта; (2) карты массово не закрывать: агентскую часть (gates/withheld/core-в-сборке/инициативная витрина) закрывать отдельным ledger-проходом с evidence на `eafbe2e7`; (3) owner-сценарии из `postdeploy-observations.md` — компактной очередью в `plans/owner_questions.md`; (4) окно наблюдения 24–48 ч (воронка инициативы, первые живые ходы); (5) VERIFIED — только по живому подтверждению.

## Ledger

| Пункт | Статус |
|---|---|
| 1. Дельта/изоляция (628, 0 некласс., services/web/WG/CFG, D1-хэши) | VERIFIED (мой пересчёт) |
| 2. Preflight (575/13/599/70/3917/87/88; W6 RED→GREEN; W2 A/B) | VERIFIED (6 прогонов воспроизвёл; W2 — доп. атрибуция) |
| 3. Капчуры: (ii) CLOSED; F2 VERIFIED; F4 приемлемо; F5 | **PARTIAL (10/50)** |
| 4. Включение (gates/core/try/withheld/initiative) | VERIFIED; `style.policy` — дефект |
| 5. Дефект №1 (диагноз+объём) | CONFIRMED (единственный не-awaited; фикс `68cd05b2` в master) |
| 6. Первая попытка (авто-откат, следов нет) | VERIFIED + ниточка F3 |
| 7. Dropdown-атрибуция | WG-введение подтверждено; каузальный toggle — за DROPDOWN-WG |
| 8. Docs/evidence findings | REQUIRED (кодировка, хеш, F5-скан, W6-фикстура, F3) |

**Итог:** релиз как tree-port и включение — независимо подтверждены; для `Approved` недостаёт: правки дефекта №1 (мини-релиз), добора F5, docs-правок и hardening деплой-скрипта; поэтому **Needs Fixes** с узким составом.
