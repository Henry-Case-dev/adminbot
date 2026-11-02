# MEME-JOKE-SPEECH - независимое ревью сервисного слайса (Reviewer, 03.11.2026)

Кандидат: ветка feat/meme-joke-speech, код a1f0f9a0 (a1f0f9a00705c08b38ec684557148a08b75888b8),
документы ae72735b, база b8d96a06. Рабочий каталог чистый (незакоммиченных правок нет).
Основание: plans/owner_inputs/2026-11-03-meme-joke-speech-layers.md (дословно),
arch/joke-speech-layers.md, отчёт Builder reports/w-joke-speech.md.

Область: сервисная часть пакета (этап B мемов и проверка обычной текстовой инициативы).
web/**, API-маршруты и миграции в кандидате не менялись.

## 1. Вердикт

APPROVED по поведению сервисного слайса / MAP_SYNC_REQUIRED (PM).
Реализация выполняет дословное требование владельца, блокирующих дефектов поведения нет.
Формальный релизный гейт пройти нельзя, пока PM не заведёт в строгой карте строки и пин
этого дополнения (см. п.7). Витринная часть "показать ревизии в диагностике" остаётся
за пакетом P4 (MEME-UI-FIELDS, строки PENDING): этим слайсом дополнение целиком НЕ закрыто.

## 2. Реальный payload этапа B (захват моего собственного пробника)

Метод: боевой путь consider_chat -> _default_joke -> _joke_system_prompt, фейковый
транспорт считает llm.generate; конфигурация владельца: глобальные документы и чатовые
оверрайды Core/Expression/Style Policy, Humor Craft с выключенными bureaucratic_logic
и unexpected_analogy, job_id="job-probe-fixed". Источники персоны подменены на границе
данных (БД в прогоне нет), сам блок собирает штатный bot_persona.resolve_character_block.

Захваченный payload (system 2924 симв.):

    system_sha12 (payload)          = 86f7b450c114
    system_sha12 (журнал speech)    = 86f7b450c114   <- совпадает
    manifest_id                     = 5e908af3c13281d9
    core        = r41.8a959786a60e (чатовая редакция, core_detail=compact:document_default)
    identity    = 58c1f361ea087b62
    expression  = c40a7b39520f (чатовая заметка "Речи и характера")
    style_policy= g4.b8f409be7c97|c12.8f84c0c3d4dc (глобал и чат)
    humor       = b2444d2932e0 (ревизия слоя humor_craft)
    technique   = deadpan, humor_status = rendered
    user        = выжимка ровно (в system выжимки нет)

Порядок блоков в system (позиция первого вхождения): задание 0 -> Core 130 ->
Persona 155 -> Speech_Base 467 -> Humor Craft 2142 -> Style Policy hint 2313.
Задание первое, речевые слои дописаны после него и не вытеснены.

Слои из манифеста и журнала (rendered в моём прогоне): channel_contract:channel_canon,
core, identity, channel_contract:speech_base (781 симв. = базовая речь и HUMOR_TEXT),
expression, humor_craft (359 симв. = текст приёма), style_policy_hint.
Пропуски названы кодами: self_model_folded_into_identity, style_requests_absent,
lessons_absent, speech_absent, no_l1_plan_in_genre, expression_examples_absent,
samples_disabled, channel_output_not_required. Дублирования нет: каждый маркер
(задание, Core, Persona, HUMOR_TEXT, текст приёма, чатовая заметка выражения)
встречается в system ровно один раз.

Выжимка аналитическая: system этапа A равен MEME_SUMMARY_SYSTEM_PROMPT, в нём нет ни
Core, ни персоны, ни Speech_Base, ни HUMOR_TEXT.

## 3. Ровно один вызов на этап B

Счётчик generate на попытку: шаги ["meme_summary","meme_joke"], всего 2 вызова,
meme_joke = 1. Повторный прямой вызов compose_speech_system с тем же входом счётчик
не увеличил (2 -> 2); mca_humor_craft.layer_calls(technique) == 0. Композер не получает
клиента модели вообще, поэтому второй LLM-вызов конструктивно невозможен.

## 4. Humor Craft: ротация по включённым техникам

Владелец выключил 2 из 5 техник, в ротации остались 3: absurd_escalation, deadpan,
literalism. На 60 разных job_id получены ровно эти 3, ни одной выключенной; повтор того же
job_id даёт ту же технику (детерминизм, без LLM и без случайности).
Осталась одна включённая: выбирается только bureaucratic_logic.
Ось humor_craft_enabled выключена: техника пустая, слоя нет. Приём виден в журнале
(speech.technique) и совпадает с текстом в payload.

## 5. Обычная текстовая инициатива (Writer не переделывался)

Боевые методы generate_initiative_reply -> _initiative_persona_block ->
_l2_write_answer -> _compose_speech_system (подменён только memory и алиасы):
1 Writer-вызов, чатовый Core r41.8d5cb11776a4 в payload (глобальный отсутствует),
чатовая заметка выражения есть (глобальная нет), чатовый hint стиля есть;
manifest.versions совпадают с резолверами (core/style/expression).
Чатовое выключение оси стиля: style_policy_hint пропущен с style_policy_disabled,
остальные слои живы. Чатовое выключение оси Core: core_disabled, личность жива.
Перенос тела личности байт-совместим: bot_persona.resolve_character_block ==
DirectChatService._initiative_character == _initiative_persona_block (305 симв.,
персона и Character_Rules), ctx возвращается тем же.

## 6. Диагностика, целостность контрактов, тесты

facts.joke.speech содержит 14 ключей: composer, system_sha12, manifest, core,
core_detail, identity, expression, style_policy, humor, technique, humor_status,
layers, skipped, off_axes. В versions ключа humor НЕТ (проверено на манифесте),
ревизия берётся из трассы слоя. В журнал не попадают сырые тексты: Core, персона,
выжимка, прикол и HUMOR_TEXT не найдены. prompt_composer.py и mca_humor_craft.py
не тронуты (пустой diff), миграций и SQL нет.

Fail-open (композер недоступен, смоделировано): composer="failed", system равен прежней
инструкции байт-в-байт, Core и персоны нет, user = выжимка, прикол всё равно один вызов,
system_sha12 в журнале от фактического legacy-payload.

Тесты: читал assertions, не только имена. Проверяются реальный payload и равенство
system_sha12 журналу, равенство layers/skipped манифесту, причины из SKIP_REASONS,
ротация, выключенные оси, "правка промпта не вытесняет личность", чатовые оверрайды
инициативы. Вакуумных проверок и моков проверяемой границы нет: подменён транспорт
(это и есть предмет проверки), композер и резолверы настоящие.

Прогоны (кандидат a1f0f9a0, venv проекта):
* test_meme_joke_speech_layers.py и test_initiative_speech_layers_chat_overrides.py: 12 passed;
* test_soul1_w5_observer_gates, test_meme_pipeline_stages, test_evol014_meme_initiative,
  test_soul1_composer_layers, test_soul1_core_composer_integration, test_soul1_w4_humor_craft,
  test_bot_persona, test_persona_prompt, test_quota_removal_composer,
  test_soul1_composer_parity_off: 169 passed;
* широкий -k "meme or initiative or prompt or composer or persona": 1243 passed, 2 skipped, exit 0.
Предсуществующих падений не обнаружено, поэтому сверка с базой b8d96a06 не потребовалась.

## 7. Блокирующее для релиза (не для Builder): карта не знает про дополнение

plans/progress_scope.json: OI-2026-11-03-MEME-JOKE-SPEECH-LAYERS зарегистрирован,
но reconciled: false. В requirements-map.json (strict_evidence=true) этого дополнения нет
вообще: в amendments только автоудаление команды /meme, слайса MEME-JOKE-SPEECH нет,
slice_candidate_pins без него, candidate_commit = старый ceb49b56.
Фактический прогон гейта:

    requirements_gate.py check --stage review --slice MEME-JOKE-SPEECH --candidate a1f0f9a0
    FAIL: review scope has no requirements: MEME-JOKE-SPEECH
    FAIL: candidate mismatch; map candidate_commit must match --candidate
    stage=review inventory=116 manual=21 scoped=0 errors=2

Что должен сделать PM (одна ограниченная сверка, без нового цикла разработки):
1. записать поправку в amendments со ссылкой на immutable-источник;
2. завести строки приёмки: сборка через единый композер и наследование слоёв; реальный
   payload и совпадение system_sha12; задание не заменяет личность; ровно один вызов и ноль
   в композере; ротация приёма по настройкам владельца; диагностика facts.joke.speech и
   ревизии; обычная инициатива с чатовыми оверрайдами; закрепить этот отчёт как evidence
   на a1f0f9a0;
3. добавить слайс или пин кандидата, поставить reconciled: true;
4. отдельной строкой владельцу витрины: "показать в карточке" (P4) со статусом PENDING.

## 8. Незакрытое и некритичное

* P4 (отдельный пакет, PENDING): в карточке "Инициатива -> Мемы" ревизии и манифест ещё не
  показываются; серверная часть (analytics.last_joke) готова, веб не менялся. Владелец
  просил именно "показать": это обязательство P4, а не этого слайса.
* После выката (PET_PROJECT, без новых гейтов): /meme в реальном чате, в журнале speech.*
  непусты, Inspector provider_calls(step="meme_joke") показывает тот же system.
  Проверка возможна только в проде, на одобрение слайса не влияет.
* Некритично: при выключенном на уровне чата flags.persona_enabled слой личности помечается
  причиной identity_absent (гейт в resolve_gates берётся глобальный). Поведение и подпись
  совпадают с Direct, на payload не влияет.
* Некритично: _speech_facts вызывается вне try сборки, поэтому теоретический сбой чтения
  манифеста стоил бы попытки мема (сейчас все поля это dataclass-атрибуты). Наблюдаемых
  падений нет, предложение в бэклог, не блокер.
* Ротация приёма не учитывает уместность (L1-плана у жанра нет): зафиксировано архитектурой,
  слой остаётся подсказкой, уместность решает персонаж.

## 9. Три столпа доказательств

* Implementation: прочитан фактический путь consider_chat -> _default_joke ->
  _joke_system_prompt -> prompt_composer.compose_speech_system; проверены слои _compose,
  resolve_gates, sha12/_versions, mca_humor_craft.resolve_ref,
  bot_persona.resolve_character_block и делегат _initiative_character.
* Test validity: прочитаны assertions новых и затронутых тестов; проверяют реальный payload,
  хеш, журнал, ротацию, выключенные оси и инициативу; вакуумных проверок нет.
* Independent challenge: собственные пробники на реальном коде с фейковым транспортом:
  чатовые оверрайды и пустое значение с откатом на глобал, выключение осей
  Core/Expression/Humor/Style на уровне чата, длинная правка задания (1620 симв., слои
  не сжались: Core 23, персона 68, приём 359 симв. как в базовом прогоне), fail-open
  композера, отсутствие утечек текста в журнал, ротация на 60 job_id, инициатива
  с боевыми методами Writer.
