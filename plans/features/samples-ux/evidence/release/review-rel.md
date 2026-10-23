# REV-REL-258100 — ревью релизного поезда 2.58.100 (read-only lane, 20.10.2026)

## ВЕРДИКТ: **Approved** (push + deploy; миграция v37 применится при старте; постдеплой: healthz / данные библиотеки сохранены / ERR=0)

Кандидат: **acc285d77d03c7adbf5527dc7f0fa9e9904fed8e** (HEAD master) поверх прод 2.58.99 `7142ffcf` (предок — проверено `git merge-base --is-ancestor`, exit 0).
Состав поезда 7142ffcf..acc285d7 (6 коммитов): `29b91004` samples-ux main (review Approved 20.10) → `cc7ac8d7` docs canary 4/4 → `27b1165a` R1-фиксы → `532a2d24` docs ledger 77 строк → `c849dbf4` 06G.3 attribution → `acc285d7` бамп+docs.

## 1. Коммит-гигиена
- `27b1165a` — ровно 4 файла по предписанию REV-SAMPLES-UX: mca_sample_library.py (restore_preview +include_tombstoned), test_samples_factory_persist.py (+1 REGRESSION), app.css (бейдж nowrap, flex-wrap), speech.py (why category=). Версионных файлов нет.
- `c849dbf4` — 8 файлов, все в зоне 06G.3: factcheck_attribution.py (NEW 342), orchestrator (этап 3b), tool_router (v2-ветка), smartmodule_phrases (+пул), mca_events (+1 reason), mca17c (пины), map 06G.3 VERIFIED, тест-файл (NEW 610). Factcheck-каноны/чужая логика не тронуты.
- `acc285d7` — 34 файла = 30 proc (27 пинов + settings.py + README + F8-meta) + 4 docs/evidence. Samples-ux файлов в бампе НЕТ. Арифметика «31-file proc set» сходится: 30 в бампе + mca17c (два пина: reason 301→302 и APP_VERSION) в c849dbf4 — задокументировано в сообщении бампа.
- Остаточные «2.58.99» — только в исторических evidence (легитимно); в живом коде/пинах 0.

## 2. Независимые прогоны на acc285d7 (py .venv)
| Прогон | Результат |
|---|---|
| test_samples_factory_persist + test_samples_acceptance | 20 passed (12+8) |
| test_samples_categories (реальный путь v36+данные→v37, бэкфил) | 12 passed |
| test_samples_ui_e2e (playwright) | 1 passed |
| ui_p0a_ux_speech_compact_e2e (скрипт) | failures=0, POST=22 |
| test_factcheck_attribution_cfg06 + mca17c + categories | 41 passed (21+8+12) |
| test_factcheck_orchestrator_cfg06 + unified_core_route_coverage | 34 passed |
| test_soul1_w6_speech_ui (why-эндпойнт) | 23 passed |
| settings import | APP_VERSION == 2.58.100 |
| F8 --check | CHECK OK: реестр 582 == REGISTRY |
| README | v2.58.100 |

## 3. Контрпример-проверки
- Why-эндпойнт после фикса повторяет runtime resolve_refs (humor с техникой + general без) — сверено с исходником resolve_refs: паритет.
- Attribution-блок в tool_router строго внутри `if v2:` (строки 2451–2497) → OFF-паритет; exception-path fail-open к поведению 2.58.99 (без регресса privacy-контракта W4, который уже был).
- reason 302 реально в REASON_CODES, пин 301→302 с провенансом (mca17c зелёный).
- DDL v37: аддитивный (ALTER +6 колонок, table_info-guard, идемпотентный бэкфил); все NOT NULL имеют DEFAULT ('legacy'/0/0) → **старый код 2.58.99 на v37-схеме работает** (INSERT заполняет дефолты, SELECT старые колонки не трогает). Откат кода с v37-БД безопасен; повторный выкат — миграция идемпотентна.
- 06G.3: честный miss → фраза + attribution_not_found + return ДО платного поиска (agg.searches==[] покрыто тестом); privacy external_safe_claim (_strip_privacy) на всех v2-ветках; публичные фигуры — обычный контур.
- Рабочее дерево грязное ТОЛЬКО plans/docs (+scratch) — код-дерево чистое, прогоны валидны для кандидата.

## 4. Privacy/live/откат
- Сетевых/telegram-отправок в новом коде нет (factcheck_attribution.py: 0 совпадений send/http); miss-фраза идёт через СУЩЕСТВУЮЩИЙ send_chunked_reply оркестратора (обычный продуктовый путь, не агентские отправки).
- owner_live_checks §7 — пункты владельцу, не гейты (standing PET_PROJECT-правило).
- 7142ffcf достижим; рубеж release/fix-2.58.99 создаётся при push (DevOps).

## 5. Findings
Блокеров нет. Ненакладные:
1. (info) Пин APP_VERSION в mca17c уехал в коммит 06G.3, а не в бамп → промежуточный c849dbf4 имеет красный test_app_version_not_bumped до acc285d7. Финальное дерево консистентно, отклонение раскрыто в сообщении бампа и pins24-summary. Не блокер (деплой поезда по HEAD).
2. (info) F8-meta HEAD=27b1165a (не acc285d7) — соответствует прецеденту 2.58.99 (F8-meta 8f220b60 при деплое 7142ffcf); каталог-ключей c849dbf4 не добавляет.

## 6. DevOps-уведомление
Подтверждено: evidence/release/ddl-check.txt («Deploy applies the migration at service start; DevOps notified separately») + README (ΔDDL v36→v37 ожидаем/аддитивно/идемпотентно/data-preserving; focused-samples-migration 12p).

## Команды для оркестратора
- Push: `git push origin master` + создать рубеж `release/fix-2.58.99` на `7142ffcf` (аннотированный тег).
- Deploy: штатная процедура deploy_commands.txt (креденшелы не печатать; один recon ~15с + один основной прогон; статус по HTTPS /healthz).
- Постдеплой: healthz == 2.58.100; данные humor_samples сохранены (v37 бэкфил, legacy-строки на месте); ERR=0; фактчек v2-флаг не трогать (уже ON с 2.58.99).
- Откат: checkout/tag 7142ffcf + рестарт (v37-схема совместима со старым кодом — см. §3).
