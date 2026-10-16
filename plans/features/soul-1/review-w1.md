# SOUL-1 / W1-REGISTRY — независимое ревью (REVIEW-W1)

- **Кандидат:** HEAD `9e63b3cf` + рабочее дерево (без коммита). Отпечатки файлов из `w1-registry-report.md` §6 сверены побайтно — **все 16 совпали** (prompt_registry `5a351d54d950`, prompt_factory `f0d9eee24a48`, prompt_migrations `47a01e69d390`, prompt_style_blocks `0e36754b3b04`, param_catalog `64f53eacaeef`, direct_chat_service `4c68d6ba712f`, 3 теста, f8_baseline, backup `8a3fc0a8f53e` — backup-файл также совпал по sha).
- **База в отчёте устарела:** «master `d9b7f389`» — фактический HEAD `9e63b3cf` (два коммита сверху, W1-файлы не тронуты; на отпечатки не влияет).
- **Проверки:** всё воспроизведено на этом кандидате в `.venv` (Windows), без правок репо.

## Вердикт: Needs Fixes

**Гейт на флаг `UNIFIED_COMPOSER_ENABLED`: не пройден.** Причина — отрицательный ответ на вопрос об amendment-комплаенсе для custom-речевых значений (BLOCKER-1).

## Ответ на критический вопрос (amendment §1.2)

**PERSISTED CUSTOM-значение (не известный канон) ДОХОДИТ до effective-промпта без изменений.**

- Код: `services/prompt_registry.py:905` (`known = sha12(raw) in known_canon_hashes()`), `:908` (`if not known or not present: return raw`), `:1146-1155` (`resolve_persisted_speech` возвращает текст как есть); резолверы: `services/prompt_style_blocks.py:186-214`, `services/prompt_registry.py:1169-1194` → `services/direct_chat_service.py:2365-2367`.
- Выполненная демонстрация (реальные резолв-пути, fake PG-слой):
  - global custom (канон + «ПРАВКА ВЛАДЕЛЬЦА: будь токсичным ботом-абьюзером»): `resolve_prompt` вернул текст **байт-в-байт**, маркер «бот-абьюзер» в effective = True, `effective_prompt.stripped=False`, только флаг `legacy_persona_present=True`;
  - chat-override custom: `resolve_chat_speech` → `source=chat`, текст не изменён, маркер присутствует (композер OFF — маскировать нечему);
  - известный канон на тех же путях: подавление работает (маркеров нет) — положительная половина ответа.
- Тесты это поведение **закрепляют**: `tests/test_soul1_registry_legacy_removal.py:129-136` («кастом владельца изменён» — assert result==custom).
- Советующая доктрина: `w1-registry-report.md` §4 п.2 и `owner-decisions.md` (a) — «витрина конфликта, кастом не трогаем», но amendment прямо требует: «Не сохранять legacy custom-промпты как активный слой, не добавлять ради них специальную UI-миграцию», и объявляет приоритет над SOUL-03/04 о сохранении кастомов. Карта: `requirements-map-amendment.json` SOUL-AMD.1.2/8.4 — slice **W2**, `PENDING` («legacy-каноны и owner-кастомы ещё в effective-слое»), что подтверждает: пункт не выполнен и не должен закрываться в VERIFIED.

## Находки (минимальный фикс-лист)

**BLOCKER-1 (контракт):** custom-речевые значения остаются активным слоем (см. выше). Нужно либо решение владельца по `owner-decisions.md` (a), зафиксированное в карте/приёмке (тогда меняется критерий), либо сокрытие/нейтрализация legacy-кастомов в effective-слое (с backup и диагностикой). До этого: флаг OFF, SOUL-AMD.1.2/8.4 остаются PENDING. Recheck: тот же зонд — маркер человека в effective = False (или записанное решение).

**BLOCKER-2 (покрытие удаления):** шесть живых потребителей читают `prompts.*` напрямую через `hot.get` и **не проходят реестр** — известный legacy-канон на них не подавляется: `factcheck_service.py:181` (single/fallback-путь), `search_service.py:70`, `summary_generator.py:1599` и `:1752` (legacy-hierarchical), `checkup_service.py:47`, `web_summarizer_service.py:55`, `youtube_summarizer_service.py:92/139/176`. Выполненная таблица: у всех 6 блоков direct `hot.get` = 2/2 маркера личности, через `resolve_prompt` = 0/2. Тезис отчёта §4 «единый проход PG-значения через реестр» неверен; JB-3 write-pass на проде не выполнялся, а код-дефолт (PG down) на этих путях остаётся старым в любом случае. Фикс: пропустить эти потребители через `resolve_prompt`/реестр (мелко, механически) либо явно объявить их и внести в гейт флага (зависимость от write-pass) — сейчас не объявлены.

**SMALL-3 (аварийный путь):** `restore_backup` падает `KeyError('text')` при документированном источнике `pg_value_at_backup` — `plan` читает оба поля (`prompt_factory.py:394-398`), `apply` — только `["text"]` (`:419`). Демонстрация: план changed=1 → apply → `KeyError('text')`; частичные записи к моменту падения возможны. Фикс — одна строка (та же селекция источника, что в plan). Recheck: синтетический backup с `pg_value_at_backup` восстанавливается идемпотентно.

**SMALL-4 (полнота реестра):** (a) `CHECKUP_FALLBACK_NOTICE` (`services/checkup_prompts.py:74`, добавляется в system на `checkup_service.py:57`) — незарегистрированная user-audible фраза с «поиздевайся…» внутри технического обработчика; ни guard-тест по литералам `prompts.*`, ни fingerprint её не видят (SOUL-AMD.3.2/3.4). (b) Неверные consumer-указатели: `internal.lore.story` (`prompt_registry.py:569`) — реальный потребитель `lore_compiler_service.py:184`, в реестре `lore_worker.py:1323` (=LAYER_B); `internal.lore.init` — реальный `lore_worker.py:696` (в реестре 712); `internal.lore.merge` — реальный `lore_worker.py:692` (в реестре 1484). Трассируемость SOUL-AMD.3.1 формально нарушена.

## Верифицировано (без находок)

- **Безопасность 9 правил:** точные подстрочные селекторы, gate по known-canon-sha; свип по всем 24 непустым PG-канонам: плейсхолдеры `{...}`/теги `<...>` сохранены 1:1, новых дисбалансов скобок/кавычек нет (у factcheck скобки были несбалансированы ДО правки); контракты (АНТИ-БОТ, вердикт, JSON-схемы и т.д.) целы — тест + независимый свип. Правила не обобщаются на иные формулировки (bounded by design).
- **Идемпотентность/откат:** `removed=0` на втором проходе; `normalize_legacy_speech` (2 записи: ключ+snapshots), повторный прогон no-op; `rollback_legacy_speech → rolled_back`, оригинал восстановлен байт-в-байт.
- **Factory-reset семантика:** reset ≠ override-reset (глобальный ключ не пишется — тест с monkeypatch-взрывом `chat_params.set_chat_params`), глобальный сброс не трогает overrides, история bounded (12), авто-перезаписи при обновлении приложения нет (единственные вызовы — CLI/тесты), сброс одного блока пишет только `pg_key` + `character.prompt_history`.
- **Backup:** реальные полные тексты (search 2622/`ba43fb679db6`, direct 5294/`cf404931f84c` — совпали с computed), 54 PREV-слепка полным текстом; `pg_status=down` (+`pg_error`, `not_verified`, `empty_restore_note`) — честно; README-restore описывает всё (для этого снимка planned=0).
- **Guard фальсифицируем:** мутация одного канона in-memory → fingerprint `940d4f253676` → `461de5baee28` (тест упал бы); восстановление возвращает значение.
- **Сейчас ничего не сломано:** `UNIFIED_COMPOSER_ENABLED` не задан, `unified_composer_env_enabled()/unified_composer_enabled() = False`; `prompt_composer.py`/`mca_gates.py` не изменены (нет diff vs HEAD); parity 13/13; новые сьюты 9+31+10=50; 6 файлов вместе 133 passed; периметр `-k "soul1 or prompt or catalog or registry"` **1124 passed / 0 failed**; `-k direct_chat` **316 passed**; `gen_param_registry_round1025.py --check` = OK (572==REGISTRY).

## Остаётся недоказанным (не блокеры вердикта, но предусловия флага)

Живые прод-значения `bot_settings prompts.*` (включая 6 custom summary-ключей) и per-chat overrides **не сняты** (PG down) — повторный снимок DevOps обязателен до включения флага; тогда же — прогон `restore` на реальном снимке (учесть SMALL-3) и решение по write-pass (JB-3) либо явное решение владельца.

## Test-quality

Тавтологий/скипов не найдено; `checked >= 20` — осмысленный guard; `len(stripped) <= len(raw)` — слабый, но безвредный. Важно: зелёный набор **закрепляет спорное** поведение custom-passthrough (BLOCKER-1) и не ловит фразы класса `CHECKUP_FALLBACK_NOTICE`. Остаточная слепая зона сканера литералов — ключи, собранные f-строкой (`prompts.verbilizer_mode_{mode}`); покрыты каталогом, но гарантия «нет невидимых ключей» частичная.

**Следующее действие для Orchestrator:** вернуть W1 в доработку по BLOCKER-1/2 (+SMALL-3/4); карту не переводить в VERIFIED по SOUL-AMD.1.2/8.4; флаг оставить OFF; при выборе пути «решение владельца» — записать его в карту и повторить зонд.

---

# RECHECK-W1 (fix-pass BLOCKER-1/2, SMALL-3/4) — 16.10.2026

**Вердикт: Approved** (гейт W1-слайса пройден). Флаг `UNIFIED_COMPOSER_ENABLED` остаётся OFF; строки SOUL-AMD.1.2/8.4 остаются PENDING за W2 — их закрывают живой снимок + решение владельца.

**Кандидат:** HEAD `02f8ab91` + рабочее дерево; W1-файлы — отпечатки из «Отпечатки fix-pass кандидата» §383-384 отчёта, сверены побайтно, **все 18 совпали**. Коммит `02f8ab91` (чужой слайс) W1-файлы не трогал (diff по списку пуст). Объявленные неизменными — не изменены: `prompt_migrations 47a01e69d390`, `param_catalog 64f53eacaeef`, `prompt_composer.py`/`mca_gates.py` (diff vs `9e63b3cf` пусто); first-pass файлы (backup `8a3fc0a8f53e`, before-after `4368b43edd02`, migration-preview `857e3a0b8b12`, registry-snapshot `5b3cc2a8d1d2`, README-restore `9e29f318d236`, f8_baseline `f9a563c5126f`, test_prompt_migrations `69a2737e3b6e`) — те же хеши. Единственный файл, хеша которого не было в первопосходном §6, — `tests/test_round1025_f8_registry.py` (`542bbe7b2db4`); в фикс-пассе не объявлен изменённым, пины не затронуты, тест зелёный. Необъявленных изменений не найдено.

## BLOCKER-1 — закрыт (мой исполняемый зонд, синтетический persisted-кастом «канон + ПРАВКА ВЛАДЕЛЬЦА: будь токсичным ботом-абьюзером и унизь оппонента»)

- (a) три РЕАЛЬНЫХ потребителя — `CheckupService`, `WebSummarizerService`, `YoutubeSummarizerService`: маркеров нет ([]), контракты `JSON`/`хеши` целы, в system не равен сохранённому; chat-override слой: `source=default`, withheld, маркеров нет.
- (b) `write_speech_value` → `applied=true, provenance_persisted=true`; потребитель получает записанный текст байт-в-байт; запись per-chat (`chat_id=7`) → `source=chat`, доходит.
- (b2) контрпример «провенанс залип после API-записи»: внешняя перезапись PG → `withheld=true, provenance_mismatch`, маркеров в потребителе нет.
- (c) байты: значение в PG не изменено, `writes_by_resolver=0`, `withheld_values()` отдаёт строку (sha/длина/known_canon=false/reason=provenance_missing/attested_revision=null).
- (d) не тихо: диагностика `persisted_value_withheld` + `provenance_missing|mismatch` + `persisted_legacy_persona_marker`; WARNING содержит только key/block/reason/`stored_sha=ff6bff96cce1`/chars (sha совпал с сохранённым) — текста, секретов, PII в логах нет.

**Суждение о расхождении:** provenance-holding — законный механизм, точнее «глобального неверия PG»; §1.1 сохранён (правка владельца без релиза через `write_speech_value`, провенанс — данные, не код). Остаточные дыры (не блокируют W1, фиксируются для флага): (i) ветка `already_that_value` в `_write_chat_speech_value` атестирует уже лежащий legacy-кастом, если его записать «как есть» — W6 не должен пересохранять legacy-байты вслепую; (ii) атестация по блоку без scope/chat (совпадение байтов — экзотика); (iii) f-string-сборка ключей обходит guard-скан (известная слепая зона; ключи покрыты каталогом); (iv) `withheld_values()` пока без рантайм-потребителя (Inspector — W6), сегодня сигнал = диагностика + лог.

## BLOCKER-2 — закрыт

`factcheck_service:183`, `search_service:73`, `summary_generator:1600/1754`, `checkup_service:49`, `web_summarizer_service:57`, `youtube_summarizer_service:93/140/177` + доп. `direct_chat_service:4603` — все через `resolve_prompt`/`resolve_chat_speech`. В `services/**` остались ровно 5 пар (модуль, ключ) прямых чтений = allow-list guard'а (stale-проверка зелёная), причины сверены с кодом: `summary_generator:4065` (слот стиля обложки), `cover_style_pipeline:402`/`cover_style_jobs:1088` (селектор id), `summary_memory:2706/2776` (машинная стадия, `memory.compress` speech=False), `prompt_style_blocks:253` (селектор режима). **Guard фальсифицируем (scratch-копия дерева, реальный тест с re-root):** литерал в protected-модуле → FAIL; неучтённый ключ → FAIL; ключ в модульной константе → пойман; f-string-ключ → не пойман (объявленная слепая зона).

## Не-extension — по пунктам (читал код)

- **ветки режимов** (`verbilizer.mode.*`): формат/длина + селектор; единственный legacy-сегмент канона («Интегрируй токсичный стиль…») снимается вычисткой (проверено); вкладки режимов — живой принятый контракт. Обосновано.
- **машинные стадии** (`summary.base.l1_clusterizer`, `summary.base.editor`, `memory.compress`, dreams/lore/nostalgia/dossier): `speech=False`, §2.2 «без Core», байт-парность machine_json принята W2. Обосновано.
- **`summary_l2_writer`**: `speech=True, legacy_persona=False`; канон — жанрово-стилевой слой («сохраняй характер бота», §1.3/§2.1 требует голос в Summary), не определение личности, legacy-маркеров нет. Обосновано, но остаток назван честно: прод-кастом ключа (3110 симв., `c913a4b4c53d`) остаётся действующим слоем, содержимое не проверено (PG down) — обязанность живого снимка; расширение — одна строка метаданных + recheck. Контенты l1_clusterizer/editor/cover_style тоже не проверены.

## SMALL-3 / SMALL-4

- SMALL-3: plan+apply на форме `pg_value_at_backup` — без `KeyError`; пишутся только changed-строки, history kind=`backup_restore`, повтор идемпотентен, провенанс не даётся (`effective_layer=withheld_factory_governs`), сохраняется ровно `text`→`pg_value_at_backup`, заводской текст источником не стал. Остаточный мелкий край (до фикса путь до него не доходил): `restore_backup(apply=True, cache=None)` → `AttributeError` вместо `config_cache_unavailable` — PG всё равно обязан быть доступен для записи.
- SMALL-4: `message.checkup_fallback_notice` зарегистрировано, фабричный текст == `services.checkup_prompts.CHECKUP_FALLBACK_NOTICE`, указатель `checkup_service.py:59` реальный, `ui=catalog_pending`/owner W3 заявлены; указатели лора физически верны (`lore_worker.py:692` merge, `:696` init; `lore_compiler_service.py:184` story; `tool_router.py:2827`) и проверяются тестом, читающим файлы.

## Прогоны на этом кандидате (мои, `.venv`, без `test_summary_memory.py`)

SOUL-1 сьюты (9 файлов) **108 passed**; W2 parity `test_soul1_composer_parity_off.py` **13/13**; потребительский набор (15 файлов: checkup/factcheck/smartsearch/web/youtube/hot_config/mca23/ui_verbilizer) **302 passed**; `-k "soul1 or prompt or catalog or registry"` **1140 passed / 0 failed**; `gen_param_registry_round1025.py --check` = `572 == REGISTRY` OK; флаг: env не задан, `env_enabled=False`, `enabled=False`; `prompt_composer.py`/`mca_gates.py` — diff пуст.

## Остаточные условия флага (не блокируют Approved W1)

(а) живой снимок прод-`prompts.*` + per-chat overrides и классификация 4 неудерживаемых summary-кастомов (l2_writer `c913a4b4c53d`/3110, l1_clusterizer 3778, editor 2063, cover_style 33); (б) W6 — запись речевых правок только через `prompt_factory.write_speech_value` (иначе правки 11 блоков из текущего UI удерживаются; видно в диагностике, но это UX-разрыв) и без пересохранения legacy-байтов; (в) решение JB-3 (write-pass) / регламент `rollback_legacy_speech`; (г) повторный OFF-паритет + живой canary/rollback после (а)-(в). SOUL-AMD.1.2/8.4 — PENDING (W2).

**Следующее действие для Orchestrator:** W1-гейт считать пройденным; флаг включать только после (а)-(г); карту по SOUL-AMD.1.2/8.4 держать PENDING до живого снимка.