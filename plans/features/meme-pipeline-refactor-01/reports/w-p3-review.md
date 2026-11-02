# P3 MEME-MANUAL-CMD + автоудаление - независимое ревью

- Кандидат: d58537496cc129987e8eb045019909b794c11533 (ветка feat/meme-manual-cmd), база 242fbd38d99690bfab2c0f9d431cdff8dd9529dc. Рабочее дерево чистое.
- Diff: bot.py, handlers/meme_command.py (новый), services/initiative_observer.py, tests/test_meme_command_autodelete.py, отчёт линии.
- Источники: plans/owner_inputs/2026-11-03-meme-pipeline-refactor-01.md (разд. 4-8), plans/owner_inputs/2026-11-03-meme-command-autodelete.md, arch/integration-decisions.md (разд. 4 и 10), карта MEME-CMD-*, MEME-CMD-DELETE-*, MEME-ACC-10/11.
- Окружение: Windows, Python 3.12, pytest локально, фейковый Telegram-клиент из набора линии; прод и Telegram не трогались.

## 1. Вердикт

Approved (по поведению) / MAP_SYNC_REQUIRED до релизного гейта.

Блокирующих дефектов в проверенном кандидате нет: критерии 10 и 11 ТЗ и все пять обязательств автоудаления подтверждены выполнением на этом кандидате. При этом требовательный гейт requirements_gate.py --stage review --slice MEME-MANUAL-CMD красный по канцелярской причине: 21 строка пакета в статусе PENDING, candidate_commit в карте пуст, evidence пуст. Это работа Builder/PM (записать доказательства и привязать кандидата), а не новый цикл разработки. До привязки доказательств выпускать пакет нельзя.

## 2. Три обязательных линии доказательств

- **Implementation.** Прочитан реальный путь: handlers/meme_command.py::cmd_meme (RBAC -> delete_command_message -> run_manual_pipeline -> доставка), services/meme_initiative.py::consider_chat(manual=True) (тумблеры 1301-1315, image/журнал 1321-1331, квота/кулдаун/тихие часы/минимум/random/in-flight 1352-1395, бронь не создаётся 1460-1462, гейт manual_bypass 1521-1523, доставка 1545-1567), services/initiative_observer.py::_meme_sender (только фото, без caption), bot.py:930-937 (роутер рядом с admin_commands_router, до menu_router), handlers/direct_chat.py:559 (текст с "/" -> UNHANDLED, команда выше не перехватывается), services/bot_commands.py (команды в меню нет), services/roles.py:120-220 (access_for).
- **Test validity.** Прочитаны тела tests/test_meme_command_autodelete.py (18 проверок): ассерты идут по записанной последовательности вызовов в общем журнале events и по строкам журнала попыток, а не по факту "мок вызван"; проверяются отрицательные исходы (не-админ - ноль вызовов), таймаут удаления, отсутствие traceback (record.exc_info is None), отсутствие caption, отсутствие утечки промпта и прикола. Дополнительно прочитан tests/test_meme_pipeline_stages.py::test_manual_bypasses_quota_cooldown_activity_random_and_gate: там facts["manual"] is True и facts["gate"] == "manual_bypass" строго. Слабое место одно (п. 8.4): в тесте линии на bypass есть дизъюнкция "... or published[-1].get("stage") == STAGE_PUBLISH", истинная всегда, поэтому "ручной" признак именно этим тестом не доказывается; его доказывают тест P1 и моя проба A.
- **Independent challenge.** Свои 12 проб (скрипты в WorkspaceData/runs/.../temp-f08c525cea/probe_p3*.py, вне репозитория) на фейковом клиенте линии: (A) админ при daily_limit=0, активном кулдауне, min_messages=99, тихих часах 00:00-23:59, закрытом publish-гейте и бросающем тумблере: события ровно ["delete","summary","joke","provider","photo"], один delete по id команды, одно фото, ноль текстов, одна попытка в журнале, в publish-строке {"gate":"manual_bypass","manual":true}, status_counts не изменился, ни одного reply_parameters; (B) удаление падает TelegramForbiddenError (реальный класс 403) и RuntimeError: тот же порядок, один delete, одно фото, ровно один WARNING с типом исключения и без traceback, без повтора; (C) реальный roles.access_for(STRANGER, chat, cache=None) даёт отказ, /meme даёт ноль событий и ноль строк журнала, ЛС-владелец собственного чата тоже без прав, ADMIN_USER_ID и local_admin проходят, исключение проверки даёт отказ; (D) image backend с причиной image_provider_unhealthy: ноль фото, ровно один короткий текст без кода, этапы не стартовали, delete первым и один; (E) два параллельных /meme в одном чате: без исключений, два фото, два удаления, две manual-попытки; (F) сбой моста (пайплайн бросает): одно общее сообщение без внутренностей, WARNING "manual run raised", удаление уже сделано. Итог 0 провалов (первый прогон дал 6 ложных "красных" - мои собственные неверные ожидания по формату журнала, где attempts() даёт строку на стадию, и по префиксу "[/meme]" в тексте лога; после исправления ожиданий зелено).

## 3. Приёмка

| Требование | Статус | Наблюдение |
|---|---|---|
| Критерий 10: /meme работает вручную, вне квот, кулдаунов и авто-триггеров | PROVEN | Проба A + test_manual_run_bypasses_quota_cooldown_and_closed_gate + test_manual_bypasses_quota_cooldown_activity_random_and_gate: квота 0, кулдаун 3600, минимум 99, тихие часы, тумблеры, random, in-flight, закрытый гейт - публикация состоялась, брони нет |
| Критерий 11: /meme недоступна не-админу | PROVEN | Полная тишина: 0 delete, 0 исходящих, 0 строк журнала (проба C на реальном access_for; T6; мутация "снять RBAC" даёт красный тест) |
| Автоудаление: ровно один delete, первым, до пайплайна | PROVEN | events == ["delete","summary","joke","provider","photo"], delete_calls == [(chat, msg_id)] (T1, проба A); мутация "убрать delete" даёт 3 красных теста |
| Автоудаление: сбой удаления проглатывается одним WARNING без traceback, без ретраев | PROVEN | 403-класс, RuntimeError, таймаут: один вызов, один WARNING с типом, exc_info is None (T3, проба B); мутация "ретрай в except" даёт красный тест |
| Автоудаление не меняет исход и число исходящих | PROVEN | При успехе ровно одно фото, при провале ровно один текст, независимо от исхода удаления (T3/T4, пробы B/F) |
| Автоудаление только на админском пути, без обхода прав | PROVEN | Удаление стоит после гейта; у не-админа его нет вовсе |
| Ответ - новое сообщение без reply-цели | PROVEN | Ни reply_parameters, ни reply_to_message_id нет ни в фото, ни в тексте ошибки (пробы A/D) |
| Успех = только изображение, без caption и follow-up | PROVEN | bot.kinds() == ["photo"], caption нет, промпт и прикол отсутствуют в исходящих (T2, набор P0) |
| Не обходятся: image backend, журнал, разрешимость бюджета, RBAC | PROVEN | Пробы C/D; image_dependency и table_present() стоят до всех manual-обходов; no_joke_budget и length_limit_unknown дают короткий текст |
| Ошибка = одно короткое сообщение без кодов, промпта, выжимки, прикола | PROVEN | _FAILURE_TEXT и _GENERIC_FAILURE; в тестах и пробах проверено отсутствие кодов и служебного текста |
| Команда не рекламируется (меню и справка) | PROVEN | services/bot_commands.py не тронут (_COMMANDS = summary/info/menu), в handlers/info.py упоминаний нет, тест test_meme_command_is_not_advertised_in_bot_menu |
| Ярлык joke и четыре новых кода причины в service-словаре | PROVEN (service) | set(MEME_STAGE_LABELS) == set(STAGES), joke даёт "генерация прикола"; SKIP_JOKE_FAILED, SKIP_JOKE_EMPTY, SKIP_NO_JOKE_BUDGET, SKIP_TEMPLATE_EMPTY резолвятся через reason_label, который реально используется services/initiative_diagnostics.py:192,210,744,1069 |
| "Сырой код не доходит до бейджа" | NOT PROVEN в этом пакете (владелец - MEME-UI-FIELDS) | Бейдж рисуется клиентским web/app.js:11257-11291 (memeStageLabel, memeSkipLabel), web/** в пакет не входит; сейчас бейдж покажет joke сырым кодом. Обязательство зафиксировано в acceptance пакета MEME-UI-FIELDS, P3 его закрыть не может |

## 4. Порядок обработчика: что наблюдалось

RBAC (см. п. 5) -> delete -> consider_chat(manual=True) -> доставка. В общем журнале событий удаление единственное и первое; при провале удаления событие delete всё равно первое, пайплайн идёт дальше, число исходящих совпадает с успешным удалением. Ни asyncio.create_task, ни добивающих фоновых задач в обработчике нет; ожидание удаления ограничено DELETE_TIMEOUT_SECONDS = 5.0.

## 5. Суждение по fail-open в RBAC

Builder заявил риск: "тишина наследует fail-open roles.access_for, если PG или кэш недоступен". Проверка по коду и выполнению:

- при полностью недоступном кэше (cache=None, худший срез) реальный access_for(99999, group, cache=None) даёт is_global_admin=False, is_local_admin=False, то есть отказ: деградация не открывает команду обычному пользователю (проба C);
- сбой самой проверки в обработчике трактуется как отказ (access_for бросает -> is_meme_admin возвращает False; тест линии и проба C6);
- внутри access_for ошибка запроса chat_admins ловится и приводит к role_chat=None: теряется грант локального админа, а не появляется чужой доступ (roles.py:193-197);
- фактический fail-open остаётся один: настоящий глобальный админ (владелец) сохраняет доступ при недоступном PG. Это корректная семантика, а не эскалация.

Вывод: для админской диагностической команды это приемлемо, не блокер. Остаточный риск только про доступность (локальный админ в группе может не пройти при недоступном PG), а не про безопасность. Замечание к формулировке отчёта линии: слово fail-open здесь звучит страшнее, чем есть; точнее "деградация сужает доступ".

## 6. Что запускалось (и что переиспользовано)

Запущено самостоятельно на кандидате:
- tests/test_meme_command_autodelete.py - 18 passed;
- tests/test_meme_pipeline_stages.py + tests/test_evol014_meme_initiative.py - 58 passed;
- tests/test_p0_meme_image_only.py, test_admin_commands.py, test_bot_commands.py, test_p0_initfix_initiative_observer.py, test_p0_init_arch_fix_observer.py, test_soul1_w5_observer_gates.py, test_asap8_v63_b01_initiative_observer.py, test_initiative_delivery_telemetry.py - 98 passed;
- повторный сводный прогон после мутаций (5 файлов) - 90 passed; рабочее дерево после мутаций восстановлено побайтово (git status пуст).

Переиспользовано: наборы P1 (стадии, бюджет, manual) и P0 image-only как кандидатно-совместимые; ассерты перечитаны, а не только факт "зелено".

## 7. Мутации, воспроизведённые ревьюером

| Мутация (файл восстановлен через git checkout --) | Наблюдение |
|---|---|
| убрать вызов delete_command_message | 3 теста красные (в events нет delete) |
| второй delete() в except (ретрай) | 2 теста красные (delete_calls = 2) |
| manual=True заменить на False | test_manual_run_bypasses_quota_cooldown_and_closed_gate красный |
| if not await is_meme_admin(...) заменить на if False: | test_non_admin_gets_silence_without_delete_or_pipeline красный |

## 8. Замечания (все неблокирующие, с владельцем)

1. PM и Builder, доказательства и привязка. Карта: 21 строка пакета PENDING, candidate_commit пуст, evidence пуст; requirements_gate --stage review даёт 22 ошибки. Нужно записать доказательства (тесты и этот отчёт) и привязать d5853749, затем перезапустить гейт. Поведение проверено и подтверждено; это рассинхронизация карты, не дефект кода.
2. PM, расхождение манифеста. slice-graph.json для MEME-MANUAL-CMD объявляет write-scope handlers/admin_commands.py, services/bot_commands.py, tests/test_admin_meme_command.py, а замороженный arch (разд. 4 и 10.4) требует handlers/meme_command.py, bot.py, tests/test_meme_command_autodelete.py. Реализовано по arch (верно); привести граф и план в соответствие должен PM.
3. Builder, неточность в отчёте линии. В w-p3-cmd.md (разд. 4) указан файл tests/test_meme_pipeline_refactor_01.py, которого нет; bypass-матрица живёт в tests/test_meme_pipeline_stages.py. Исправить до привязки доказательств, иначе PM привяжет несуществующий артефакт.
4. Builder, слабая дизъюнкция в тесте. test_manual_run_bypasses_quota_cooldown_and_closed_gate, строка с parse_attempt_facts(...)["manual"] is True or ... stage == STAGE_PUBLISH: второй член истинен всегда, "ручной" признак этим тестом не доказывается. Убрать or (тест P1 уже проверяет строго; моя проба A тоже).
5. PM, не считать ярлыки P5 закрытыми. MEME_STAGE_LABELS и meme_stage_label() в этом кандидате не используются ни одним продакшн-потребителем (только тесты), бейдж читает свой JS-словарь. Либо честно отнести "метку прикола в бейдже" к MEME-UI-FIELDS (P4, ждёт освобождения web/**), либо удалить неиспользуемый дубль, чтобы не появилось двух источников правды.
6. Architect, формулировка разд. 10.1. Утверждение "RBAC - локальная проверка без сети" неточно: roles.access_for при наличии кэша делает запрос chat_admins в PG, то есть до удаления возможен сетевой roundtrip (миллисекунды; при сбое - отказ или сужение гранта). Поведение приемлемо, формулировку стоит поправить, чтобы не создавать ложного инварианта.

## 9. Преднайденный сбой test_youtube_multimodal_download_round1024

Воспроизведён на базе 242fbd38 в отдельном чистом worktree: 9 passed, 18 errors - ровно как на ветке. Причина на базе та же: фикстура патчит youtube_mod.get_smart_cache, которого в handlers/youtube.py нет; diff P3 этот файл не трогает. К пакету отношения не имеет, в блокеры не идёт, отдельная задача в backlog.

## 10. Что осталось вне пакета (честно)

- Живое исчезновение сообщения в чате владельца - свойство Telegram и наблюдение владельца (PET_PROJECT, стоячее правило; в карте live_required=false). Реализация и все ветки отказа проверены, живого прогона в Telegram не было.
- web/**: метка joke и четыре кода в бейдже - P4 (MEME-UI-FIELDS), заблокирован линией COG-MAP S3.
- Поля промптов и числа L/T/J в админке и API - P2 (вне этого пакета).

## 11. Следующий шаг

Orchestrator: пакет MEME-MANUAL-CMD готов к привязке доказательств. PM и Builder записывают evidence по 21 строке и candidate_commit=d5853749, исправляют пп. 2-4, затем requirements_gate.py check --stage review --slice MEME-MANUAL-CMD --candidate d5853749 --repo . должен стать зелёным. Только после этого - релиз по стоячему правилу проекта и живое наблюдение владельца (не блокирует).
