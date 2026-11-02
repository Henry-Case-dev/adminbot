# P3 `MEME-MANUAL-CMD` — команда `/meme`, автоудаление, ярлыки P5 (service)

Ветка `feat/meme-manual-cmd`, база `242fbd38` (P1 `MEME-PIPE-CORE` + merge).
Пакет карты: `MEME-MANUAL-CMD` (P3) + service-часть P5. Требования:
`MEME-CMD-ADMIN-ONLY`, `MEME-CMD-BYPASS-GATES`, `MEME-CMD-KEEP-SAFETY`,
`MEME-CMD-DELETE-ON-RECEIPT`, `MEME-CMD-DELETE-ADMIN`,
`MEME-CMD-DELETE-FAILOPEN`, `MEME-CMD-DELETE-NO-BYPASS`,
`MEME-CMD-DELETE-NO-NOISE`.

## 1. Где живёт обработчик

| Что | Где |
|---|---|
| Роутер + `setup_meme_command(db, llm, bot)` | новый `handlers/meme_command.py` (арх. §4) |
| Регистрация | `bot.py:59` (импорт) и `bot.py:933-936`, рядом с `admin_commands_router`, до `menu_router` и catch-all |
| Пайплайн | существующий `services.meme_initiative.consider_chat(..., manual=True)` — второй ветки нет |
| Доставка | тот же binding, что у авто-инициативы (`InitiativeObserverRunner._meme_sender`) — только фото, без caption |
| RBAC | `services.roles.access_for` + `settings.ADMIN_USER_ID` |
| Ярлыки | `services/initiative_observer.py`: `REASON_LABELS` (+4 кода), `MEME_STAGE_LABELS` (+`joke`), `meme_stage_label()` |

В меню `/` и справку команда не добавлена: `services/bot_commands.py` не
тронут, тест фиксирует отсутствие `meme` в `_COMMANDS`.

`prompt_override` не передаётся (ревью P1, п.5): шаблон берётся из слоёв
настроек, `model_chars` резолвит сам пайплайн — `L` не теряет потолок модели.

**Расхождение артефактов (к сведению PM, не конфликт ТЗ):** `slice-graph.json`
указывает write-scope `handlers/admin_commands.py` и
`tests/test_admin_meme_command.py`, а arch §4/§10.4 (замороженное решение,
на него ссылается задание) — новый `handlers/meme_command.py`,
регистрация в `bot.py` и `tests/test_meme_command_autodelete.py`. Выполнено
по arch; текст scope в графе стоит привести к arch.

## 2. Порядок обработчика (заморожен арх. §10.1)

`RBAC → (тишина не-админу) → delete → pipeline → delivery`.

Наблюдаемый порядок в общем журнале событий теста (один список `events` на
все фейки — бот, суммаризатор, генератор прикола, провайдер картинки):

```
["delete", "summary", "joke", "provider", "photo"]
```

`delete_calls == [(chat_id, message_id_команды)]`, ровно один вызов.

## 3. Автоудаление: поведение при сбоях

- Один `message.delete()` через `asyncio.wait_for(..., DELETE_TIMEOUT_SECONDS=5.0)`.
- Успех → INFO `[/meme] command deleted | chat=<id> msg=<id>`.
- Любой сбой (403/400, >48 ч, сеть, уже удалено, таймаут) → ОДИН WARNING
  `[/meme] command delete failed (<ТипИсключения>) | chat=<id> msg=<id>`,
  без traceback (`record.exc_info is None` в тесте), без повторов, без
  фонового добивателя, пайплайн не отменяется.
- Ответ всегда НОВОЕ сообщение без reply-цели: ошибка — `bot.send_message(
  chat_id=..., text=...)`, успех — фото через `telegram_send.send_photo`
  (без caption). Исход доставки не зависит от исхода удаления.

Проверено тестами: `RuntimeError` (нет прав), `TelegramBadRequest` (сообщение
не найдено), таймаут (`DELETE_TIMEOUT_SECONDS` временно 0.01 с при медленном
фейковом `delete()`): число исходящих сообщений одинаково (1 фото), delete —
ровно 1 вызов.

## 4. Bypass-матрица (`manual=True`, арх. §4)

| Ограничение | Обходится? | Доказательство |
|---|---|---|
| суточная квота (`daily_limit=0`, день уже израсходован) | да | фото пришло, брони нет: `status_counts` не изменился |
| кулдаун (`cooldown_seconds=3600`, прошлый провайдер-вызов 60 с назад) | да | публикация состоялась |
| минимум сообщений (`min_messages=99`, окно 1) | да | публикация состоялась |
| тихие часы (`00:00-23:59`) | да | публикация состоялась |
| тумблеры инициативы/мемов (`enabled=False`, `initiative_enabled` бросает) | да | функция-тумблер вообще не вызвана |
| случайный триггер | да | `random_source` не спрашивается |
| in-flight | да | guard только при `not manual` |
| гейт публикации (закрыт) | да | `publish{gate:"manual_bypass"}` |
| RBAC | **нет** | не-админ: ни удаления, ни генерации |
| готовность image-модуля/провайдера | **нет** | «нет backend» → одно короткое сообщение, фото 0, провайдер не вызван |
| наличие журнала попыток | **нет** | `schema_absent` → короткое сообщение |
| разрешимость бюджета длины | **нет** | `no_joke_budget`/`length_limit_unknown` → короткое сообщение |

Ошибка в чат — ровно одно короткое сообщение по карте «код → бытовая
причина» (`_FAILURE_TEXT`), коды/промпт/выжимка/прикол не уходят; текст
проверяется на отсутствие `image_generation_failed`, `MEME_IMAGE_PROMPT`,
«прикол» и любого упоминания удаления.

**Где физически лежат доказательства (для привязки PM).** Файла
`tests/test_meme_pipeline_refactor_01.py` в репозитории нет и не было — это
опечатка в arch §7/§8, не артефакт. Реальные файлы:

- `tests/test_meme_command_autodelete.py` — команда `/meme` целиком:
  `test_manual_run_bypasses_quota_cooldown_and_closed_gate` (квота 0 +
  кулдаун + минимум сообщений + тихие часы + тумблеры + закрытый гейт) и
  `test_manual_run_does_not_bypass_image_backend_availability`;
- `tests/test_meme_pipeline_stages.py` — сам пайплайн с `manual=True`:
  `test_manual_bypasses_quota_cooldown_activity_random_and_gate`,
  `test_manual_keeps_image_and_schema_gates`.

## 5. Ярлыки (P5, service-часть)

- `REASON_LABELS` + `joke_generation_failed`, `joke_empty`, `no_joke_budget`,
  `template_empty` — `obs.reason_label(code) != code`.
- `MEME_STAGE_LABELS` + `meme_stage_label()`: покрытие ровно
  `set(meme.STAGES)` (включая `joke` → «генерация прикола»), неизвестная
  стадия честно отдаётся кодом.

**Что осталось на P4 (файл `web/app.js` заблокирован линией COG-MAP S3):**
одна строка в `memeStageLabel` (после `summary: 'Выжимка',`):

```js
          joke: 'Генерация прикола',
```

Если бейдж должен показывать и причины по-человечески, там же в
`memeSkipLabel` нужны четыре кода (`joke_generation_failed`, `joke_empty`,
`no_joke_budget`, `template_empty`) — это тот же файл и та же правка P4;
service-словарь уже их резолвит (`reason_label`, диагностика/API).

## 6. Тесты

`tests/test_meme_command_autodelete.py` — новый, **18 проверок**
(CONTRACT + REGRESSION), все с общим журналом событий:

1. T1 порядок `delete → summary → joke → provider → photo`, ровно 1 delete,
   `message_id` = id команды;
2. T2 успех: ровно 1 исходящий — фото, текстов 0, `caption` нет, промпт и
   прикол в чат не попали;
3. T3 сбой удаления (`RuntimeError`, `TelegramBadRequest`): пайплайн тот же,
   исходящих столько же, один WARNING с типом исключения и без traceback;
4. таймаут удаления: ожидание ограничено, WARNING `(TimeoutError)`, пайплайн
   идёт дальше;
5. T4 сбой пайплайна при успешном и проваленном удалении: ровно 1 текст,
   фото 0, об удалении ни слова;
6. T6 не-админ (в т.ч. `is_dm_owner`): 0 delete, 0 исходящих, в журнале нет
   ни строки; гейт `is_meme_admin` (global/local/ADMIN_USER_ID) и
   fail-closed при сбое `access_for`;
7. bypass-матрица (таблица §4): `manual_run_bypasses_quota_cooldown_and_closed_gate`
   — журнал содержит РОВНО `considered/eligible/summary/joke/image_generation/
   publish`, факты публикации строго `{"gate": "manual_bypass",
   "manual": true}` (без дизъюнкций), брони нет; плюс «нет image backend» →
   короткая ошибка. Пайплайновые обходы отдельно —
   `tests/test_meme_pipeline_stages.py`;
8. `/meme` отсутствует в меню `_COMMANDS`;
9. ярлыки: покрытие всех стадий + четыре кода.

Мутационная проверка (файлы восстановлены побайтово, «мутация → красный»):

| Мутация | Результат |
|---|---|
| удаление ПОСЛЕ пайплайна | T1 падает |
| `manual=True` → `False` | bypass-тест падает |
| повторный `delete()` в `except` (ретрай) | T3 падает (delete_calls=2) |
| убрать `joke` из `MEME_STAGE_LABELS` | тест ярлыков падает |
| не отправлять сообщение об ошибке | T4 падает |
| снять RBAC-гейт | T6 падает |
| `gate_reason = "manual_bypass"` → `"gate_ok"` (потеря маркера) | bypass-тест падает |
| `"manual": bool(manual)` → `False` в фактах публикации | bypass-тест падает |

Строгая проверка маркера (итерация 2 после ревью P3): в bypass-тесте убрана
дизъюнкция `... or published[-1]["stage"] == STAGE_PUBLISH` (она была истинна
всегда, т.к. фильтр уже выбирал `outcome == "published"`). Теперь проверяются
ровно список стадий журнала и факты публикации
`{"gate": "manual_bypass", "manual": True}`; обе мутации выше дают красный
тест, после восстановления — 18 passed.

Прогоны (эта ветка):
- `pytest tests/test_meme_command_autodelete.py` — **18 passed**;
- фокусный набор `test_meme_command_autodelete + test_admin_commands +
  test_meme_pipeline_stages + test_p0_meme_image_only +
  test_evol014_meme_initiative + test_bot_commands +
  test_asap8_f5_module_truth + test_summary_handlers` — **176 passed**;
- широкий `pytest tests -k "meme or initiative or observer or command or help
  or menu"` — **847 passed, 1 error**; ошибка
  `test_youtube_multimodal_download_round1024::...::test_allowlist_blocks_branch`
  — преднайденная и к задаче отношения не имеет: `handlers/youtube.py` и в
  `HEAD` не содержит `get_smart_cache`, который патчит фикстура (18 ошибок
  в изолированном прогоне файла на этой же базе).

## 7. Что НЕ сделано / вне пакета

- `web/**` не тронут: `joke` в `memeStageLabel` и четыре кода в
  `memeSkipLabel` — одна правка P4 (§5 выше).
- Поля промптов и API-числа L/T/J — P2; серверные стадии/аналитика — P1.
- Живой прогон в чате владельца (команда исчезла, картинка пришла) — не
  выполнялся: требует реального Telegram и разрешения на сообщения в чат.

## 8. Риски

- **R1.** «Тишина не-админу» опирается на `roles.access_for`; при недоступном
  PG/кэше он fail-open (глобальный срез), поэтому админом может оказаться
  глобальный админ — это ожидаемо, а обычный пользователь остаётся без прав.
  Сбой самой проверки трактуется как отказ (fail-closed для команды).
- **R2.** Удаление — целиком свойство Telegram (бот-админ в группе, <48 ч);
  исход не влияет на генерацию, поэтому «не удалилось» не является дефектом
  продукта, только записью WARNING.
- **R3.** `manual=True` не тратит квоту и не проверяет in-flight: параллельный
  ручной прогон того же чата возможен (это диагностика, не авто-инициатива).
