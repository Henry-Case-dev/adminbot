# SOUL-1 / AMD26 — отчёт слайса: проводка «Летописца» (рассказ о лоре) через Core + жанровую рамку

- **Lane:** AMD26-WIRING (writer, main tree; веер не запускался — одна связная
  правка; без коммита/push/деплоя).
- **Кандидат:** рабочее дерево поверх `434b7ac5` (HEAD на момент слайса;
  параллельная read-only верификация W5 уже закоммичена и не затрагивалась).
- **Покрытие клаузы:** `SOUL-AMD.2.6` — «лор, истории» закрыты тестами на
  существующем публикующем пути; сны/глубокий сон/«рассказы о них» — честно
  записаны как внутренние машинные стадии (§2.2) без публикующего пути.

## 1. Что сделано (простыми словами)

Единственный существующий публикующий путь из остатка клаузы — «Летописец»
(«Бот, расскажи историю про…»): бот собирает рассказ о лоре и публикует его
в чат **готовым текстом** (safe-HTML, минуя Writer, — `ctx.lore_compiled`).
До слайса этот путь работал на собственном каноне («Ты — саркастичный
летописец…») — то есть нёс **отдельную скрытую личность** и не получал Core,
что и запрещает уточнение владельца (§2.1/§2.3).

Теперь system для этого пути собирается тем же общим композером, что
«Ностальгия» (`mca_authorial_speech.authorial_system`, writer `lore_writer`,
жанр `lore`):

* **композер OFF** (текущий заводской режим) — прежний канон публикуется
  **байт-в-байт** (паритет W2; ни одного нового байта в модель);
* **композер ON** — в system попадают заводской жанровый слой
  `genre.lore.rules` + Personality Core + Style Policy-hint, а канон остаётся
  функциональной базой (HTML-разметка, UPD-ветка «Свежак», «даты/имена/
  порядок — только из данных», объём 3–6 абзацев). Второго «писателя» не
  появляется: сборка идёт через единственный композер, манифест виден в
  Inspector (`writer=lore_writer`).

Внутренние машинные стадии (дистилляция снов, «мост» глубокого сна,
генерация авто-лора, досье, эпизоды) не тронуты: по §2.2 того же уточнения
они обязаны оставаться точными и нейтральными.

## 2. Клауза → путь → было/стало → доказательство → честная граница

| Путь | Что было | Что стало | Тест / артефакт | Честная граница |
|---|---|---|---|---|
| **Лор, истории** — «Летописец» (рассказ о лоре, публикация в чат) | system = собственный канон «саркастичного летописца»; Core и жанровые правила не подключались | `authorial_system(writer="lore_writer", genre="lore")`: OFF → канон байт-в-байт, ON → жанровая рамка + Core + канон | `test_lore_story_off_parity_byte_for_byte`, `test_lore_story_on_gets_core_and_lore_genre`, `test_story_write_contract_unchanged_with_composer_on`; RED-транскрипт `evidence/amd26/red-before-wiring.txt` | Фактическая публикация всё ещё требует включения оси владельцем; байтовый паритет проверен тестом на реальном `compile()` |
| **Ностальгия / воспоминания** | — | — | Тесты W4 (`test_nostalgia_path_*`), перепрогнаны | Проведено в W4; слайс не менял |
| **Сны, глубокий сон** | внутренние машинные стадии: убеждения/парадигмы пишутся в память; в чат ничего не публикуется | Без изменений (§2.2: «точность без художественных домыслов») | `test_untouched_machine_stages_are_marked_in_registry`; поиск публикующих путей (см. `paths-coverage.md`) | Публикующего пути «рассказ о сне» в продукте нет; он не выдуман |
| **«Рассказы о них»** | — | — | `test_dream_and_story_frames_stay_ready_contract` | Рамка `genre.dream.rules` — зарегистрированный Factory Default; контракт появления пути готов (`authorial_system`) |
| **Творческие тексты** | — | — | `test_wired_and_pending_paths_are_visible_in_registry_notes` | Отдельного канонического пути нет (Direct — Core канала, AMD.2.3); рамка `genre.story.rules` готова |

Разбор каждого пути клаузы (включая не-human-facing) — `evidence/amd26/paths-coverage.md`.

**Реестр (дисциплина «No Hidden Behavioral Prompts»):** note-блоки и списки
потребителей обновлены по факту: `genre.lore.rules` (проведена на пути
Летописца; +потребитель `LoreCompilerService.compile`), `internal.lore.story`
(проведён через композер, канон остаётся базой), `genre.dream.rules`
(внутренние машинные стадии, рамка готова), `genre.story.rules` (нет
отдельного публикующего пути), `internal.dream.distill` (машинная стадия;
публикующего пути нет). Новых блоков и новых параметров каталога нет —
Δ каталога = 0 (`evidence/amd26/catalog-check.txt`: `CHECK OK: реестр 575 ==
REGISTRY`).

## 3. Файлы и отпечатки (sha256_12, final, рабочие байты)

| Файл | sha256_12 | Роль |
|---|---|---|
| `services/lore_compiler_service.py` | `6255c2b97d69` | проводка: `authorial_system(writer="lore_writer", genre="lore")` + fail-open канон |
| `services/prompt_registry.py` | `4b0ef89007ef` | note/consumers блоков `genre.*`, `internal.lore.story`, `internal.dream.distill`; указатель `lore_compiler_service.py:190` |
| `services/mca_authorial_speech.py` | `7705e7009eda` | не менялся (W4-байты, сверено) |
| `services/lore_prompts.py` | `68bc214899c8` | не менялся (канон Летописца — база) |
| `tests/test_soul1_amd26_authorial_wiring.py` (новый) | `b530706409dc` | 6 тестов: OFF-паритет, ON-жанр+Core, инъекция-гард, факты/запись, готовность рамок, честные границы |
| `tests/test_soul1_w4_authorial_genre.py` | `f6e3961c4372` | тест honesty-заметок обновлён под новую правду (W4-набор продолжает проходить) |
| `tools/soul1_amd26_mutation_witness.py` (новый) | `c6248fd6a022` | мутационный свидетель склеек (6 мутаций) |
| `tools/soul1_amd26_parity_witness.py` (новый) | `f009e96f4c47` | паритет осей OFF + отпечатки |
| `plans/features/soul-1/evidence/amd26/parity-off.json` | `079a2f5218bc` | оси OFF; шов возвращает канон байт-в-байт, манифест пуст |
| `plans/features/soul-1/evidence/amd26/mutation-witness.json` | `87a43512abba` | 6/6 KILLED |
| `plans/features/soul-1/evidence/amd26/focused-tests.txt` | `6b86f899e9a8` | 56 passed (4 файла) |
| `plans/features/soul-1/evidence/amd26/perimeter.txt` | `88b4b1de3446` | 3908 passed / 0 failed |
| `plans/features/soul-1/evidence/amd26/catalog-check.txt` | `1bcf2a5ce429` | `CHECK OK: реестр 575 == REGISTRY` |
| `plans/features/soul-1/evidence/amd26/frozen-assets.txt` | `a8337831d93e` | polygon/`#lg-lens`/`--lg-*` — без изменений (web не тронут) |
| `plans/features/soul-1/evidence/amd26/red-before-wiring.txt` | `746ae13f8c06` | RED: до проводки ON-сборка не получала Core |
| `plans/features/soul-1/evidence/amd26/paths-coverage.md` | — | разбор путей клаузы |

LF-инвариант: все изменённые/новые файлы слайса — LF-only (CRLF=0, сверено
побайтно).

## 4. Матрица прогонов

| Прогон | Команда | Результат |
|---|---|---|
| Фокус слайса (4 файла: AMD26 + W4-жанры + round1020 + registry completeness) | `py -3 -m pytest tests/test_soul1_amd26_authorial_wiring.py tests/test_soul1_w4_authorial_genre.py tests/test_lore_compiler_round1020.py tests/test_soul1_registry_completeness.py -q` | **56 passed** — `evidence/amd26/focused-tests.txt` |
| Периметр | `py -3 -m pytest -k "webapp or ia_ or soul1 or round1025 or round1024 or ui_ or glass or persona or prompt or registry or catalog" -q` | **3908 passed, 0 failed** — `evidence/amd26/perimeter.txt` (базлайн W4 3869 — на более раннем коммите; прирост включает тесты W5-слайса) |
| Паритет OFF | `py -3 tools/soul1_amd26_parity_witness.py` | оси FALSE; шов возвращает канон байт-в-байт, манифеста нет — `parity-off.json` |
| Мутационный свидетель | `py -3 tools/soul1_amd26_mutation_witness.py` | **6/6 KILLED** — `mutation-witness.json` |
| Каталог параметров | `py -3 tools/gen_param_registry_round1025.py --check` | `CHECK OK: реестр 575 == REGISTRY` — Δ = 0 |
| Замороженные ассеты | `py -3 tools/soul1_w4_frozen_check.py` | polygon/`#lg-lens`/`feDisplacementMap`/`--lg-*` — `same`; web не менялся |
| Живой UI / node-сторожа | — | **не требовались: web не затронут** (ни одной правки в `web/`); node-тесты входят в периметр и зелёные |

## 5. RED → GREEN (честная фальсификация)

1. **RED (репро дефекта):** на HEAD-версии `lore_compiler_service.py` при
   композере ON тест `test_lore_story_on_gets_core_and_lore_genre` падает:
   `assert CORE in system` → в system только прежний канон «летописца»
   (`evidence/amd26/red-before-wiring.txt`). То есть до слайса публикация
   действительно шла без Core.
2. **GREEN:** после проводки — 56/56 фокусных, периметр 3908/0.
3. **Мутации склеек (6/6 KILLED, временные копии дерева):**
   M1 — снят OFF-гейт композера (паритет подменяется сборкой);
   M2 — рамка выпала из base; M3 — на публикующем пути потерян жанр;
   M4 — материал чата вшит в system (инъекция-гард);
   M5 — `{topic}` не подставляется (тема-адресат уходит в модель как есть);
   M6 — в хранилище уходит канон вместо рассказа (payload искажён).

**Негативы в тестах:** пользовательский материал (диалоги/факты/прошлая
история) не попадает в system — только в user-блок (`INJECT` строка);
запись истории сохраняет тот же текст/ключ темы/last_ts; число LLM-вызовов
на путь не изменилось (`llm.calls == 1` в OFF и ON).

## 6. Инцидентальные находки

1. **По делу (исправлено):** правка сдвинула строку канона в
   `lore_compiler_service.py`, из-за чего указатель потребителя в реестре
   `lore_compiler_service.py:184` перестал указывать на строку с
   `LORE_STORY_SYSTEM_PROMPT` — сторож трассируемости
   (`test_soul1_registry_completeness.py`) это поймал; указатель обновлён на
   `:190` (тот же стиль, что у соседних блоков).
2. **По делу (обновлён сторож честности):**
   `test_wired_and_pending_paths_are_visible_in_registry_notes` (W4) проверял
   фразу «следующим слайсом» в заметках `genre.dream.rules`/`genre.lore.rules`;
   после проводки заметки изменены по факту. Тест обновлён на новую правду
   (Летописец проведён; сны — машинные стадии без публикующего пути; история —
   без отдельного пути) — проверка границ не ослаблена, а переведена на
   фактическое состояние.
3. **Не блокирует (unrelated/pre-existing):** `plans/features/soul-1/plan.md`
   (L438) при следующей привязке потребует строки статуса AMD.2.6 — карта
   правится родителем/PM (мне запрещено трогать `requirements-map*.json` и
   `plan.md`).

## 7. Честные границы и что осталось

- Живой канареечной проверки здесь нет и не требуется: у `SOUL-AMD.2.6`
  в карте `live_required=false` (`live_when=preprod`); фактическая публикация
  с Core начнётся, когда владелец включит `UNIFIED_COMPOSER_ENABLED` (ось
  остаётся OFF по умолчанию; паритет подтверждён).
- Сны/глубокий сон/«рассказы о них» закрыты **не кодом**, а честной записью:
  публикующего пути в продукте нет, внутренние стадии по §2.2 остаются без
  Core. Если появится путь «бот рассказывает сон», его контракт — тот же
  `authorial_system` (рамка `genre.dream.rules` уже Factory Default, тест
  готовности контракта уже есть).
- Коммит/привязка к картам — за родителем; изменения карт/плана этим слайсом
  не выполнялись.
