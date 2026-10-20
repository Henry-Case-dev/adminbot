# REV-CFG07A-F1 — независимое ревью фикса F1 (payload-чистка кастома 7 канонов)

Дата: 21.10.2026. Ревьюер: Reviewer (leaf REV-CFG07A-F1), read-only.
Кандидат: uncommitted worktree поверх HEAD `e3fd364c` (линия 2.58.101, deployed SHA e3c61445).
Runtime-дифф: `services/prompt_registry.py` (sha256_12 `b28459d008a1` — сверён),
`services/prompt_factory.py` (`46cbcc0c0c8a` — сверён); тесты: `test_cfg07a_f1_custom_suppress.py`
(`c87b04784017`, новый), `test_soul1_registry_legacy_removal.py` (`a9a2e31a51aa` — сверён).
Фактчек-каноны/лестницы: `factcheck_prompts.py`, `prompt_migrations.py` — вне диффа (git status).

## ВЕРДИКТ: **Approved** (лейн F1; прод-трасса CFG-07A.1 — за release-слотом после выката)

## Проверки (все выполнены ревьюером на текущем дереве)

1. **Data-safety** — ПАСС. Резолв-путь без записей: `provenance_state`/`attested_revision`
   только читают кэш; `suppress_legacy_speech` — чистые строковые операции. Тест (b):
   рекордирующий двойник кэша `cache.sets == []` на 7 канонах, двойной резолв байт-равен
   (идемпотентность), повторный suppress уже чистого текста — removed=0. Grep всех
   call-site: миграции (`prompt_migrations.py:497/530/600`) сознательно БЕЗ custom_clean
   (лестницы не трогают кастом — F1 живёт только в payload-слое).
2. **Эффективность** — ПАСС. `test_cfg07a_f1_custom_suppress.py`: **51 passed** (прогон ревьюера).
   Фикстуры = PREV + владельческая правка по описанию deploy.md F1; LEGACY_MARKERS
   (SF-01..13/16) отсутствуют в payload; правка владельца сохранена дословно; текст !=
   канону (нет wholesale-перезаписи). Все 7 прод-блоков withholding_required=True и в
   проде attested (иначе маркеры не дошли бы до LLM) — custom_clean-путь релевантен именно
   проде. NB: дельта фикстуры −38 симв. vs прод −35 (модель; точные байты PG не выгружались;
   правила фраз-точные — на механику не влияет). nonblocking.
3. **Регресс known-canon** — ПАСС. suppress(PREV)==ACTIVE байт-в-байт на 5 ключах
   (search/youtube/youtube_video/web/checkup; summary теперь тоже — бонус правила 13;
   direct сознательно не assert'ится: ACTIVE direct ДОБАВЛЯЕТ новый контракт-текст —
   bounded identity-фраза + блок «СЛУЖЕБНЫЕ ПОМЕТКИ», чистый suppress его не порождает).
   Флаг custom_clean — no-op на known для всех 7 в обе стороны. Known-ветка кода
   байт-неизменна (дифф-инспекция: гейт `if not known and not custom_clean`, правила 1–11
   не тронуты).
4. **OFF-паритет + W3-freeze** — ПАСС. default не тронут даже с флагом (тест (d));
   `payload_custom_clean_scope` требует source∈{chat,global}; factcheck/лестницы вне диффа;
   `factory_set_fingerprint() == 037080375ac8` (live-проверка ревьюера).
5. **Скоуп** — ПАСС. `CFG07A_PAYLOAD_CLEAN_KEYS` == ровно 7 ключей из таблицы deploy.md F1
   (байт-сверка); фактчек-кастом и неизвестный ключ не правятся (attested-путь, тест);
   factcheck/прочие блоки в custom_clean-ветку не попадают.
6. **Контракт residual(чистый кастом) ⊆ residual(активный канон)** — ПАСС, утверждение
   верифицировано по корпусу выборочно: FA-09 `[ЭТО ТВОЯ ТЕКУЩАЯ КОМАНДА]` в direct —
   легитимный контракт target-marking («ТЕКУЩАЯ КОМАНДА (СТРОГО): считай инструкцией»);
   FA-16 теги (`<Global_Context>`, `<Conversation_Thread>`) — блок «КАК ЧИТАТЬ КОНТЕКСТ»;
   FA-18 `{max_symbols}` — шаблонный контракт в 6 канонах; MB-12 `execute_web_search` —
   инструкция инструментов; MB-13 alt «языковая модель» — цитата ЗАПРЕТА в блоке
   «АНТИ-БОТ (СТРОГО ЗАПРЕЩЕНО)». Это FORBIDDEN-класс для ОТВЕТОВ модели (эхо в речи),
   но в байтах канона — легитимные инструкции; subset — правильный контракт (чистка не
   оставляет маркеров сверх легитимной базы канона).
7. **Обновлённый SOUL-1 тест** — ПАСС, не ослабление: attested override остаётся действующим
   слоем (source=chat), владельческая правка цела, retention/fallback байт-цел; старое
   утверждение «attested chat-override байт-в-байт» кодировало ровно снимаемое поведение.
   Вне-скоуп байт-прозрачность attested покрыта `test_soul1_registry_completeness` (пакет ниже).
8. **Прогоны ревьюера** (py -3 -m pytest, это дерево):
   `test_cfg07a_f1_custom_suppress` **51 passed**; `test_soul1_registry_legacy_removal` +
   `test_cfg07_backstage_contract` **96 passed**; `test_unified_core_route_coverage`
   **18 passed**; `test_samples_{categories,acceptance,factory_persist}` **32 passed**;
   `test_prompt_migrations` + `test_soul1_legacy_custom_preserved` +
   `test_soul1_registry_completeness` **58 passed**.
   `test_outgoing_guard_round1022` — 2 failed воспроизведены ревьюером: ImportError
   aiogram.types (локальная версия aiogram), ни один telegram-файл в диффе —
   unrelated/pre-existing, вне кандидата F1.
9. **Гигиена** — ПАСС с заметкой. Runtime-дифф == ровно 2 сервиса; тесты == 2 файла;
   sha256_12 всех 4 файлов == evidence Builder'а. Worktree дополнительно содержит
   ПОСТОРОННИЕ tracked-правки plans/*.md|json (asap8-v6-3, samples-ux, cfg-06,
   workflow_state.md, mca-17c) и untracked-мусор (_upd.py, node_modules/, package.json,
   .playwright-mcp/) — НЕ часть F1: в коммит F1 не включать.

## Related-nonblocking (запрошен release-слотом): suppress(ACTIVE direct, global)

Подтверждено экспериментом ревьюера: suppress(ACTIVE_direct, source="global") — **не no-op**:
правило 1 срезает легитимную identity-фразу НОВОГО канона («Ты — токсичный, саркастичный и
циничный участник чата (бот-абьюзер). Ты »). НО математически идемпотентен (f(f(x))==f(x)):
терминология «не идемпотентен» в f1-custom-suppress.md неточна по форме, по сути факт верен.
Классификация: **related-nonblocking, pre-existing** (known-ветка F1 не менялась; сегодня
прод-кастомы PREV-базе — identity в payload отсутствовала и до фикса; OFF-паритет цел:
default-путь identity сохраняет). Материализуется, если владелец сойдёт к новому канону в
persisted-слое: payload будет гасить identity-фразу (расхождение factory-путь vs
persisted-путь). Рекомендация: отдельный bounded-фикс правила 1 (различать старую/новую
форму identity-предложения) ИЛИ осознанное решение владельца — вне скоупа F1.

## Прочие incidental (nonblocking)

* Фикстура правки — модель (−38 vs −35): честно задокументировано Builder'ом; для
  прод-трассы (после выката) рекомендуется сверка фактических payload по реальным PG-байтам.
* Проба «extra-marker-only custom» с кавычками-ёлочками не чистится — правило 13 фраз-точное
  (ASCII-форма, как в прод-байтах и корпусе): bounded by design, не дефект.

## Связка вердикта

Кандидат: worktree-дифф 4 файлов поверх `e3fd364c` (сверены sha256_12). Любое изменение
`prompt_registry.py`/`prompt_factory.py`/обоих тестов инвалидирует это ревью — recheck.
Постдеплой-проверка фактических payload 7 маршрутов (CFG-07A.1) — за release-слотом/DevOps
после выката; до неё родитель не DONE (READY_FOR_LIVE-семантика сохраняется).
