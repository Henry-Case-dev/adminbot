# SOUL-PREP — проверка подготовки релиза SOUL-1 — РЕВИЗИЯ R2 (18.10.2026)

## Привязка (exact candidate)

| Поле | Значение |
|---|---|
| Артефакт | `plans/features/soul-1/soul-release-prep.md` — 93 строки, коммит `b4ea6779` (единственный файл) |
| Прод / релиз-база | `0b7a0aca` (2.58.84) |
| Кандидат | `b4ea6779`/`db6a3d0a`; runtime == `6094a2cf` (в изолированном worktree `git diff 6094a2cf HEAD -- services web` = пусто) |
| Репетиция | `OPENCODE_WORKFLOW_SCRATCH/soulprep-r2` (worktree на `b4ea6779`), скрипт `.../review-soul-prep/r2_probe.py`; после проверки worktree удалён, дерево не менялось |
| Директива-коррекция | `plans/features/soul-1/source-release-correction-2026-10-18.md` (5 пунктов + требование к отчёту) |

## Итог R2: **Needs Fixes** (4 микроправки в одном файле, кода не менять)

## F1 (R1) — **закрыт** (проверено исполнением)

- `POST /api/config` для некаталоговых `flags.*` → 422: `get_by_pg_key('flags.unified_composer_enabled')` = `None`, а `web/api/routes.py:1176–1178` (цитата в документе верна) даёт 422; из SOUL-1-флагов в каталоге только `flags.initiative_diagnostics_publish_enabled` (`param_catalog.py:2566`).
- PG **не hot**: `hot_config.get` читает in-memory `ConfigCache`; полный `reload()` — только in-app админ/роли (`config_cache.py:743–874`), `set/set_many` обновляют лишь свой ключ. Порядок «PG-запись ДО graceful-рестарта» подтверждён репетицией: после `.env` и до рестарта композер остаётся OFF; после рестарта (`ConfigCache.init → _load_all`) — ON.
- SQL-шаблон §4 верен: `bot_settings(key TEXT PK, value JSONB NOT NULL, category TEXT, updated_at)`; jsonb-кодек пула (`pg_db.py:642–647`) даёт `jsonb true → True`, `jsonb false → False`; предупреждение «jsonb-bool, не строкой» обосновано — строка `'"false"'` читается как truthy (`bool('false')=True`).
- Репетиция последовательности (env+PG → рестарт → verify → откат): pre-deploy composer/craft/library/feedback/initiative = OFF, core/style = ON (дефолты); после рестарта env+PG — composer/craft/library/feedback = ON; откат «убрать env + рестарт» гасит все четыре; PG=`false` действует (ось AND); инициатива — env-половина из шага 1, дальше `POST /api/config` hot. Колонки Hot?/«откат» §4 соответствуют коду по каждой оси.
- **Остаётся один пробел (F4):** verify-шаг 3 через `GET /api/speech/overview → gates` не покрывает `HUMOR_CRAFT_ENABLED` (обязательный ON по директиве п.4) и ось инициативы: в `_gate_state()` ключей `humor_craft_enabled`/`initiative*` нет (мой прогон `sp._gate_state()` — 10 ключей: composer/core/style/library/feedback/experience_lessons/smart_verbalizer_modes/response_plan/persona/character_layers).

## F2 (R1) — **закрыт**

§2 переписан: «рекомендованный безопасный дефолт — НЕ “решение владельца”», OQ-4…OQ-8 — `TO_ASK` (`plans/owner_questions.md`) ✓; §6.3 включает `SOUL-AMD.1.2/4.6/7.2` ✓; §7 корректно называет пять вопросов открытыми и не блокирующими релиз ✓. Нит (non-blocking): формулировка «(не переанкорить; **все PENDING**)» относится к выборке, а не ко всем PENDING (фактически 77 + 35 = 112 обязательных PENDING) — уместнее сослаться на агрегат §6.4.

## F3 (R1) — **закрыт**

97 флагов ✓ (стр. 14); 288 строк = 268 обязательных (127 VERIFIED / 29 READY_FOR_LIVE / 112 PENDING) + 20 контекстных ✓ (стр. 83, совпадает с `workflow_progress.py --json`); подписи блобов исправлены — `45f07428`/`8b42cd96`/`3b616c1f` названы блобами W6-коммита, цель указана как `bfec633a`/`aca59123`/`d0e232e5` ✓; предупреждение о прогонах только в изолированном worktree есть ✓ (чужие правки WIN-GLASS-P0 в основном дереве, 86 против 87 JS-файлов ✓).

## Директива владельца 18.10 (пп.1–4) — встроена, кроме F4/F5

- **п.1 (legacy не в effective, только backup; авторские настройки сохранить)** — подтверждено исполнением: для всех 11 ключей класса удержания `resolve_speech_value(pg_key, canon, source='global', cache=None)` → `withheld=True`, `source=default`, **в effective нет legacy-маркеров** (мои `eff`-хеши совпали со стендом лейна: factcheck `2f61c20e3eaa`, search `b74c40b30ec1`, checkup `b5295b0c250a`, direct `45b531879b50`, narrator `95141f190d8b`); chat-источник тоже удерживается; кастомы `summary_editor`/`verbilizer_default_mode`/per-chat `summary_cover_style` не удерживаются и **не меняют текст** (авторское сохранено); `verbilizer_mode_deep_research` — вычистка без удержания. Стенд лейна добавляет: per-chat `summary_system_prompt` 3484 рантаймом вообще не потребляется (резолвится глобальный ключ).
- **п.2 (payload-верификация = precondition)** — в §5 заявлена ✓, но **F4**: (а) ссылка `evidence/soul-release/payload-verification.md` — мёртвая (такого файла нет; артефакты лейна — каталог `payload-verification/`: `stand-output.txt/json`, `stand.py`, `focused-tests.txt` = 96 passed, head `b4ea6779`); (б) критерии закрытия не названы: в стенде `summary_editor` и per-chat `summary_cover_style` — «content not captured / conflict unknown», а вне класса удержания остаются маркерные блоки из Python: `message.smartmodule.chat_persona` (это открытый пункт AMD.4.6(iii)), `style.bot_knowledge`, `internal.lore.story`, `internal.nostalgia.candidate`. Директива п.2 прямо требует проверки источников PG/Python/фабрика/fallback — их надо включить в критерии закрытия precondition.
- **п.3 (все готовые оси сразу, без канареек)** — §4/§5 соответствуют; «деплой всё OFF» корректно трактуется как изоляция релиза, не канарейка.
- **п.4 (Humor Craft + Feedback обязательны; кандидатная оценка — условно)** — обязательность в §4 отмечена ✓, но verify для craft см. F4. **F5**: строка кандидатной оценки ждёт подтверждения от PAYLOAD-VERIFY, тогда как факт проверяем в коде: `services/mca_humor_craft.py:444` `evaluate_candidates` реализован (≤2 кандидата, ≤1 вызов, таймаут 20 с, честный no-op) и покрыт юнит-тестами (`tests/test_soul1_w4_humor_craft.py:300`, `:332`), но **вызовов в рантайме нет** (по `services/web/tools` — только определение). Значит включение оси сейчас не даёт эффекта → по п.4 «не реализован [в рантайме] → не блокировать», ось оставить OFF и сказать это в отчёте; решение не должен принимать payload-лейн.

## Что остаётся на релизный прогон (не блокеры этого ревью)

Живой graceful-рестарт + `GET /api/speech/overview` на ветке; `POST /api/config` 200 для инициативы; `confirm_publish`; закрытие payload-precondition по расширенным критериям (F4); прогоны §5 (node 86/86, parity 13/13, registry 575, периметр/embedding/fs/W6/W7/frozen — ранее подтверждены, повтор на ветке).

## Ledger R2

| Пункт задания | Статус |
|---|---|
| 1. F1: механика включения/отката (код + репетиция + §4) | VERIFIED; остаточный пробел verify → F4 |
| 2. F2: атрибуция/§6.3/§7 | VERIFIED |
| 3. F3: 97 / 288 (268+20) / блобы / изоляция | VERIFIED |
| 4. Директива 18.10 (пп.1–4) | п.1 VERIFIED; п.3 VERIFIED; п.2 → F4; п.4 → F5 |
| Правки F4 (мёртвая ссылка + критерии закрытия + verify craft/инициативы) | **FAILED** (3 строки) |
| Правки F5 (фактический статус кандидатной оценки) | **FAILED** (1 строка) |

Переиспользовано: стенд лейна SOUL-PAYLOAD-VERIFY (`stand-output.txt/json`, `focused-tests.txt` — мои прогоны и хеши совпали), review-fs (13/13 отпечатков), W7+FS прогоны. Недоступно локально (вне лейна): живой прод-рестарт, `GET /api/speech/overview` на сервере, Telegram-наблюдения.
