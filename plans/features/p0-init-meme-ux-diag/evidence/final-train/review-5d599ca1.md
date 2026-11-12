# Review 5d599ca1

Вердикт: Approved

Кандидат: 5d599ca1 (код 2d41f2b3). База продакшена 6c11fc08. Предыдущее ревью 262f7f18 снято этой проверкой только в части BAN-CONFLATE.

Дифф от 262f7f18: web/api/initiative_publications.py, tests/test_initiative_publications_api.py и два документа привязки. services/meme_initiative.py, initiative_diagnostics.py, web/app.js, index.html, app.css, e2e и JS-тест побайтно те же (git rev-parse совпал попарно). Новых эндпоинтов, колонок, флагов и настроек нет. Поле generated в строке списка аддитивное. published и delivered считаются по-прежнему по исходу и факту доставки.

Implementation. generated вычисляется в _meme_attempts_grouped: нужен пройденный этап image_generation и терминал не failed плюс image_generation_failed. Счётчик суммирует это поле, а не наличие publish. Одна попытка даёт не больше единицы.

Test validity. Новый тест требует generated false у old-1 и generated 1 у стенда, где картинка доказана только у J1. Старый тест теперь требует true у G2 и false у G3. Возврат правила по этапу publish красит новый тест (4 вместо 1) и не красит старый: именно поэтому новый тест нужен.

Independent challenge. Отдельно от old-1: publish/skipped/cooldown с непустым родителем и без картинки даёт generated false. publish/published с message_id, но без этапа картинки, остаётся доставленным и не становится генерацией. Картинка плюс конфликт даёт generated true и delivered false. Отказ генерации даёт false. Две строки image_generation в одном job дают одну группу и один флаг, не двойной счёт. Мутация вернула старое правило, новый тест покраснел, байты возвращены, оба теста снова зелёные.

Одобрены: P0IM-BAN-CONFLATE; ранее проверенные и не изменённые P0IM-ID-FINISH, P0IM-ID-CONC, P0IM-PB-VOCAB, P0IM-PB-COUNT, P0IM-PB-STEP. P0IM-PB-LLM только в части честного null. Полный пункт промптов, messages, запроса картинки и формата не принят.

Прогоны: pytest publications и diagnostics 79 passed. Узкий набор удержания в test_evol014 7 passed. Два целевых теста после возврата мутации 2 passed.

Остаток: живой экран и Browser Use в этом круге не гонялись, это не новый дефект. Подпись изображения шире, чем успешные картинки, и остаётся вне этого патча. Если в группе нет этапа image_generation, голая publish не считается генерацией даже при исходе published. Это честный недосчёт без доказательства, не возврат старого завышения.

