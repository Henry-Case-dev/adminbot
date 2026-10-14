# Отчёт ревью — F13 `native-reply-media-context-round1024`

**Approved**

Коммит: `da928d9` (родитель `07644db`). Шаг 5 раунда 10.24 (UPD4-A-1, ADR-1024-14).
Объём коммита: `config/settings.py`, `services/media_marker.py` (новый), `services/chat_context.py`,
`services/thread_chain.py`, `services/direct_chat_service.py`,
`tests/test_native_reply_media_context_round1024.py` — 6 файлов, +526/−9.

Ревью пройдено: spec.md, ADR-1024-14, tasks.md (T-2291…T-2298, T-2332),
`plans/features/round1024-upd4-architecture.md` (§2, §4.1, §6, §7, §9),
`plans/current_task.md` UPD4 кластер A (стр. 274–279; значения не цитирую),
`git show da928d9 --stat` / `git diff da928d9^ da928d9`, полный прогон pytest.

---

## 1. Резюме

Ядро F13 сделано правильно и с необходимым инвариантом «нет медиа ⇒ байт-в-байт».
Медиа-маркер вынесен в единый тонкий модуль `services/media_marker.py`, три рендера
(`thread_chain`, `chat_context`, `<Current_Question>`) встраивают его строго **до** прежней
проверки на скип, а при флаге OFF и/или отсутствии медиа код идёт ровно по старой ветке.
Утечек публичных URL/`file_id`/токенов нет — реф только внутренний (`tg:<digits>`/`msg:<digits>`),
тип санитизируется до `[a-z_]`≤20. Границы F14 соблюдены: `tool_schemas.py`, `tool_router.py`,
`handlers/**` не тронуты. Полный pytest — **7681 passed, 0 failed** (заявленное число совпало),
`git diff --check` чист.

Блокирующих дефектов нет. Ниже — остаточные замечания уровня Low/информационных (не блокируют приёмку).

---

## 2. Findings

### [Severity: Low] — не блокирует
File: `services/media_marker.py:35`
Location: константа `MEDIA_TYPES`
Problem: `MEDIA_TYPES` не используется ни в модуле, ни в тестах, ни в других файлах
(`grep` по репозиторию — только определение). При этом санитайзер `_sanitize_media_type`
**не** сверяется с этим словарём: `media_marker("garbage")` вернёт `[медиа: garbage]`
(токен валиден по F14-регексу `[a-z_]{1,20}`). Заявленный «единый словарь токенов» фактически soft.
Why it matters: следующий потребитель (F14) может решить, что контракт гарантирует один из
восьми токенов БД, тогда как при битом импорте появится произвольный `[a-z_]`-токен.
Required fix (опционально, до закрытия T-2295): либо валидировать по `MEDIA_TYPES`
(неизвестное → `other`), либо убрать константу и честно описать контракт как «санитизация, не enum».
Не является spec-нарушением: spec §4.1 прямо допускает «санитизируется до `[a-z_]`».

### [Severity: Low] — не блокирует
File: `services/media_marker.py:89-101`
Location: `row_media_marker`
Problem: docstring «Никогда не бросает» неточен: в `try` обёрнут только `row_get`,
а `is_media_type`/`media_marker` вызываются вне `try`. Для значений из SQLite (str/None)
это безопасно, но формальная гарантия fail-open (spec §3.6) на 100% не покрыта.
Required fix (опционально): обернуть весь корпус либо скорректировать docstring.

### [Severity: Low] — не блокирует
File: `tests/test_native_reply_media_context_round1024.py:207-213`
Location: `test_transcript_text_hint_preserved_with_marker` (T-2332)
Problem: тест проверяет лишь то, что пользовательский текст «транскрипт» и маркер сосуществуют
в блоке. Это слабее заявленного T-2332 («сигнал выжимки vs транскрибации»): фактически
классификация фразы — задача F19/T-2348, а F13 обязан лишь **не терять** текст при добавлении
маркера. Отдельного «сигнала» в контракте F13 нет и не требуется.
Why it matters: оценка задачи T-2332 выглядит «сильнее», чем реально проверено.
Required fix (опционально): переименовать тест/комментарий в «text hint preserved alongside marker»
либо добавить кейс с длинным текстом, чтобы проверить, что начало текста (где стоит фраза-намёк)
не вытесняется маркером при капе.

### [Severity: Info]
File: `services/media_marker.py:104-136`, `services/direct_chat_service.py:1241-1252`
Location: `message_media_type` / `_render_current_question`
Problem: `message_media_type` не смотрит `caption`. Для live-сообщения «видео + caption»
(`message.text is None`, `message.caption` непуст) маркер в `<Current_Question>` **будет** добавлен.
Формально D4/spec §3.5 говорят «маркер только при пустом тексте, caption не трогаем»; на
DB-рендерах (`thread_chain`/`chat_context`, где caption лежит в колонке `text`) это соблюдено
и покрыто тестами, а в `<Current_Question>` caption и раньше не рендерился (использовался только
`message.text`), поэтому байт-эталон не задет.
Why it matters: поведение полезное (LLM видит видео), но не описано; это осознанное расширение
поверх D4 буквально.
Required fix (опционально): зафиксировать в docstring `_render_current_question`, что caption-медиа
live-сообщения маркируется (т.к. caption исторически не входит в блок), либо осознанно оставить как есть.

---

## 3. Контракт медиа-маркера (§4 spec) — чекбоксы

- [x] `services/media_marker.py` создан как единственный источник контракта.
- [x] Формат `[медиа: {type}]` / `[медиа: {type} tg:{digits}]` / `[медиа: {type} msg:{digits}]`.
- [x] Реф строго внутренний: `_REF_RE = ^(?:tg|msg):\d+$`; URL/`file_id`/токены отбрасываются
      (`media_marker("video", "https://…")` → `[медиа: video]`, тест `test_ref_outside_format_dropped`).
- [x] Санитизация: `[^a-z_]` вырезается, ≤20, пусто → `other`; инъекция `[`/`]`/переносов невозможна
      (`test_media_marker_sanitizes_broken_type`, в т.ч. «video]\n<<< …» → `[медиа: video tg:5]`).
- [x] `MEDIA_MARKER_RE` — ровно контракт F14: `^\[медиа: (?P<media>[a-z_]{1,20})(?: (?P<ref>(?:tg|msg):\d+))?\]$`.
- [x] API: `is_media_type`, `media_marker`, `row_media_marker`, `message_media_type`,
      `media_context_enabled` — все присутствуют.
- [x] `message_media_type`: video/video_note→video, photo/voice/audio/animation/sticker/document —
      словарь совпадает с `handlers.summary._detect_media_type` (порядок photo/video иной, но
      вложения взаимоисключающие — фактического расхождения нет).
- [x] R16: нет рефа → `[медиа: {type}]` без сегмента.
- [x] R17: в контекст/логи не попадают публичные URL/`file_id`/токены; debug-логи без контента.

## 4. Встраивание — чекбоксы

- [x] `thread_chain.collect_thread_chain`: `item_id` вычисляется **до** скипа; `text = row["text"] or ""`;
      пусто + флаг ON → `row_media_marker`; прежний `if text:`. Семантика raw/truthiness сохранена (D2).
- [x] `chat_context.format_chat_context`: `item_id` поднят выше скипа; `text = (…).strip()`;
      пусто + флаг ON → маркер; прежний `if not text: continue`. `kind="msg"`, заголовок не изменён.
- [x] `_render_current_question`: сохранены `_strip_direct_prefix`, кап
      `limits.chat_current_question_max_chars`, `escape_xml_text`. Маркеры own + `reply_to_message`;
      резерв `room = max(0, cap − len(suffix) − 1)` — маркер выживает при капе (тест `test_marker_survives_cap`).
- [x] `current` входит в `uncuttable` (`direct_chat_service.py:1640`) — блок с маркером доходит до LLM.

## 5. Байт-в-байт без медиа — чекбоксы

- [x] **ON/OFF для text-only совпадают:** окно (`test_window_text_only_on_equals_off`),
      цепочка (`test_chain_text_only_on_equals_off`), `<Current_Question>`
      (`test_text_only_equal_with_and_without_flag`).
- [x] **Медиа OFF = вывод без медиа-узла:** окно (`test_window_media_off_equals_media_removed`),
      цепочка (`test_chain_media_off_skips_node` → `[]`), Current_Question
      (`test_media_without_text_off_is_empty` → `""`).
- [x] При OFF весь маркер-блок пропускается — ветка идентична до-фичевой (флаг читается один раз
      на вызов, до цикла/рендера).
- [x] `<Current_Question>` без медиа — ровно `stripped[:cap]`; пустой без медиа — `""`.

## 6. Границы / инварианты — чекбоксы

- [x] **Зона F14 не тронута:** `services/tool_schemas.py`, `services/tool_router.py`, `handlers/**` —
      в диффе отсутствуют.
- [x] `imported-history-immutable`: только чтение `smart_messages`; DDL/записи не добавлялись.
- [x] `physical-two-call`: LLM-вызовов не добавлено (+0).
- [x] egress (`SEND_POINTS`/`SEND_ALLOWLIST`): не расширялись.
- [x] R16/R17/R18: рефы внутренние, в логах нет контента/URL/`file_id`; `current_task.md` не коммитился.
- [x] `parse_mode=None` plain-каналы: не тронуты.
- [x] **Δ DDL = 0:** схема/миграции не менялись (`media_type` уже читается всеми SELECT:
      `get_smart_message_by_tg_id:1871`, `get_recent_messages:1787`, `get_messages_around:1812`).
- [x] **Δ каталога = 0:** флаг — env-only `ClassVar`; `test_flag_default_on_and_not_in_catalog`
      проверяет `FLAG not in pc.known_param_keys()`; `test_param_catalog` зелёный.
- [x] `CONTEXT_POINTS` не изменён (`services/canonical_context.py` в диффе отсутствует);
      канонические pattern-тесты зелёные.
- [x] F1/F2/F7/F8/F9/F12/F17/F20/F21/F22: регрессий нет — полный pytest зелёный.

## 7. Тесты (T-2296, T-2332)

- [x] **(a)** маркер в цепочке/окне — `TestMarkerInChainAndWindow` (4 теста), проверяется точная
      каноническая строка `[01.01.1970 00:00 | вася [10] | tg:123]: [медиа: video tg:123]` и `msg:`-вариант.
- [x] **(b)** байт-эталон ON/OFF + OFF-медиа — `TestByteInvariant` (4 теста).
- [x] **(c)** `<Current_Question>`: видео-реплай без текста, своё видео, текст+видео, кап,
      text-only byte-equal, OFF — `TestCurrentQuestion` (7 тестов).
- [x] **(d)** user-content для tool-loop: маркер + `tg:`-реф парсится `MEDIA_MARKER_RE` (`ref == "tg:123"`).
- [x] **(e)** границы/безопасность: `is_media_type`, санитизация, отбрасывание рефа, caption-медиа
      не тронут (окно и цепочка), дефолт флага и отсутствие в каталоге.
- [~] **T-2332** (`test_transcript_text_hint_preserved_with_marker`): покрывает сохранение текста-намёка
      рядом с маркером, но не проверяет классификацию «выжимка vs транскрипт» (это зона F19/T-2348) — см. Low-находку.
- [x] Тесты не тавтологичны для (a)–(e): проверяются точные строки, парсинг регексом и реальные
      OFF-ветки, а не только «поле существует».

## 8. Полный прогон

```
.venv/Scripts/python.exe -m pytest -q
7681 passed, 1 warning in 113.63s
```

Целевой модуль: `tests/test_native_reply_media_context_round1024.py` — **24 passed**.
`git diff da928d9^ da928d9 --check` — чисто (exit 0).
Предупреждение — Starlette/httpx deprecation, к F13 не относится.

---

## 9. Вердикт

Функционально F13 решает заявленную задачу: факт нативного медиа и внутренний реф доходят до LLM
через цепочку реплаев, окно контекста и `<Current_Question>`; при отсутствии медиа вывод
байт-в-байт прежний; OFF-рубильник возвращает старое поведение; границы с F14 и все инварианты
раунда соблюдены. Найденные пункты — Low/info и не нарушают spec.

Контракт/инварианты/тесты — приняты. T-2297 (Reviewer) закрыт; T-2298 (@DevOps) — вне ревью.

**Approved.**
