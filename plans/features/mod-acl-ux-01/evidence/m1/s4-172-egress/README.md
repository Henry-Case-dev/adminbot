# MAC-S4-172 (egress) — секрет не уходит ни в чат, ни в телеметрию

Строка MOD-ACL-UX-01: `MAC-S4-172` (вторая половина; первая — лог и
`/api/status/logs` — заперта M1-B/M1-C).
База: `54546ab5b201a5d8bd169bad613e730d371fc3b9` (2.58.253), ветка
`feat/mod-acl-s4-172-egress`.

## F01 (review r1) — модель-текст отложенного resume-ответа

**Блокер `SD172-R1-F01` (IN_SCOPE, review r1 `bbd222ef…c461`).** До правки:
`DirectChatService.resume_deferred_evidence` (`services/direct_chat_service.py`,
L15816) доставлял текст модели `persona_short_reply(...)` голым
`bot.send_message` — мимо chokepoint, без маски. Путь смонтирован в продукте
(`media_readiness.set_resume_handler(self.resume_deferred_evidence)` →
worker sweep), поэтому это не «теоретический» обход, а живая отправка
пользовательского текста. Модуль лежал в `SEND_ALLOWLIST`, а обоснование
утверждало «bare-send'ов в модуле нет» — тест покрытия глушил весь модуль и
bypass был невидим.

Воспроизведение на типе (`red-base-r1.txt`, `review-r1.md` §2): посаженный
секрет в ответе модели уходит в payload Bot API дословно; тот же текст через
`telegram_send.send_text` маскируется в `***`.

**Правка (минимальный эквивалент, поведение сохранено):**

```python
-            await bot.send_message(chat_id, text,
-                                   reply_to_message_id=trigger_id or None)
+            await _tg_send.send_text(bot, chat_id, text,
+                                     reply_to_message_id=trigger_id or None)
```

Что именно меняется и почему это безопасно:
* один send (без чанкинга/разбиения) — как и раньше;
* тот же `reply_to_message_id`, тот же `chat_id`, тот же возврат
  (`Message`, ранее не использовался) и те же исключения (внешний
  `except Exception → return False` сохранён);
* добавлена только граница chokepoint (`_maybe_sanitize` =
  `log_ring.sanitize` → `sanitize_outgoing` → `bot.send_message`), т.е. ровно
  то, что уже применяется к остальным ответам Direct
  (`_send_traced`/`send_chunked_reply`/`send_rich_message`). Побочный эффект —
  те же штатные чистки chokepoint'а (технические теги, `fact:`/`msg:`), что у
  любого другого ответа бота.

### Полный инвентарь отправок в `services/direct_chat_service.py` (после правки)

| Строка | Отправка | Текст | Вердикт |
|---|---|---|---|
| 2420 | `send_chunked_reply(...)` из `_send_traced` | plain-ответ модели | chokepoint (`smartmodule_utils._send_once` → `send_text`) |
| 7151, 7794, 11654 | `send_chunked_reply(...)` | ответ модели / уточнение / чанки | chokepoint |
| 11637, 11671, 11681 | `_send_traced(...)` | ответ модели (plain/safe-HTML) | chokepoint |
| 11581 | `_tg_send.send_rich_message(...)` | rich-ответ модели | chokepoint |
| 15821 | `_tg_send.send_text(...)` | **resume-ответ модели** | **chokepoint (F01, было голым `bot.send_message`)** |
| 21505, 21539 | `_tg_send.send_text(...)` | ответ/чанк | chokepoint |
| 2387/2415/2588/2598/11623/11649 | `_delivered_payload(...)` | не отправка | `_maybe_sanitize` для трассы (паритет с реальным payload) |

Других примитивов в модуле нет: `bot.send_photo`/`send_document`/
`edit_message_text`/`message.answer` — 0 (скан модуля). После правки голых
send-примитивов в модуле **0** — это закреплено тестом покрытия.

### Страж покрытия усилен (не расширен)

* `services/telegram_send.WRAPPER_ALIASES` — алиасы chokepoint'а у
  потребителей (`telegram_send`, `_tg_send`, `_telegram_send`): вызов через
  них — не голый send (иначе имя метода совпадает с примитивом aiogram);
* `services/telegram_send.SEND_ALLOWLIST_NO_BARE_SENDS` — allowlist-модули,
  в которых прямых примитивов быть не должно (`services/direct_chat_service.py`);
* `tests/test_outgoing_guard_round1022.py`: `_bare_sites()` (скан с учётом
  алиасов) + `test_allowlisted_chokepoint_modules_have_no_bare_sends` +
  `test_bare_site_scan_detects_bare_and_ignores_wrappers` (страж не слепой и
  не ложно-положительный) + проверка, что строгий набор ⊆ allowlist и не
  пересекается с `SEND_POINTS`;
* обоснование `SEND_ALLOWLIST["services/direct_chat_service.py"]`
  переписано по факту (все отправки — через обёртки; голых нет; строгий
  контроль) и закреплено тестом `test_direct_chat_service_justification_…`,
  чтобы ложное утверждение не вернулось.

### RED → GREEN (F01)

```
база 54546ab5b, новые тесты : 10 failed / 12 passed  (8 чат + 2 resume)  red-base-r1.txt
кандидат                    : 22 passed                                 green-candidate-r1.txt
```

Новые тесты F01 (`TestResumeDeferredEvidenceEgress`): посаженный секрет и
форма ошибки провайдера маскируются в фактическом payload Bot API; обычный
ответ байт-идентичен (`args[0]==10`, `args[1]==reply`,
`kwargs=={"reply_to_message_id": 5}`); без evidence отправки нет (существующее
поведение). Подменяется только LLM (`persona_short_reply`), states/readiness —
настоящие.

### Мутации r1 (`mutations-r1.txt`, откат байт-точный)

| Мутация | Результат | Откат |
|---|---|---|
| снять чат-маску | 7 failed (все чат-тесты) | `81b4cbfe…96aeb` = PRE |
| снять телеметрическую маску | 2 failed | `8a6f67b6…66361f` = PRE |
| **вернуть голый `bot.send_message` в resume** | 3 failed: 2 resume-маски + `test_allowlisted_chokepoint_modules_have_no_bare_sends` | `35f04dc2…63b211` = PRE |

### Артефакты F01

`red-base-r1.txt`, `green-candidate-r1.txt`, `guard-base-r1.txt`,
`guard-candidate-r1.txt`, `suites-base-r1.txt`, `suites-candidate-r1.txt`,
`mutations-r1.txt`, `candidate-diff-r1.txt` (диф кода и тестов), плюс текст
ревью `review-r1.md` (артефакт Reviewer, сохранён байт-в-байт).

## Что проверено и что изменено

| Канал | Путь | Вердикт на базе | Доказательство |
|---|---|---|---|
| Чат | `services/telegram_send._maybe_sanitize` — общий chokepoint (`send_text`, `edit_text_safe`, `send_rich_message`, `build_cover_article_html`) | **ДЕФЕКТ**: только `sanitize_outgoing` (технические теги), значения секретов не маскировались | `red-base.txt`, мутация `mutation-chat-redaction.txt` |
| Чат | `/debug_config` (`handlers/debug_config.py` → `services/debug_config`) — единственная allowlist-точка, печатающая настройки | уже безопасно: значение не рендерится никогда, только `configured••••last4` по каноническому `ParamSpec.is_secret_value` (`services/debug_config.py:181-235`) | `TestChatDiagnosticsAlreadySafe` (проходит и на базе, и на кандидате) |
| Чат | факты чекапа/`inspect_runtime` (`services/diagnostic_collector.py:150-171`) | уже безопасно: `output_projection.sanitize` + `known_secret_values`, fail-closed; fallback на `log_ring.sanitize` | source proof + `suites-*.txt` (`test_checkup_contract.py`) |
| Чат | ошибка провайдера в чате (`handlers/youtube.py:82,224`) | уже безопасно: `log_ring.sanitize` до отправки — прецедент того же механизма | source proof |
| Чат | статические allowlist-точки (`handlers/info.py`, `slava_presence`, персоны, медиа, ASR) | не содержат значений settings/env — статический UX-текст/байты | `SEND_ALLOWLIST` + `test_outgoing_guard_round1022` |
| Телеметрия | durable `mca_events.build_event` | уже безопасно: общий whitelist `agentic_events._safe_value` (id/code-поля — идентификатор ≤64 символов, свободный текст недостижим) + `sanitize` до записи (`services/mca_events.py:33,634-639,669-676,701-710`) | `TestTelemetryEgress` (5 тестов проходят и на базе, и на кандидате) |
| Телеметрия | `services/agentic_events` → structured log + in-memory execution graph | structured-log проходит `SecretMaskFilter` (`bot.py:22,175`); in-memory snapshot фильтруется тем же `_safe_value`. Значение из settings/env ни один из 62 вызывающих не передаёт | source proof; предел зафиксирован ниже |
| Телеметрия | `services/external_log.py:26,116-131`, `services/betterstack_handler.py:57,228` | уже безопасно: `safe_text`/`sanitize` | source proof |

## Изменение (одно решение по каждому каналу)

**Чат** — `services/telegram_send.py`: текст перед `sanitize_outgoing`
проходит существующий R17-санитайзер журнала `services.log_ring.sanitize`
(тот же, что уже используется для показа ошибки провайдера в чате).
Второго санитайзера нет — это закреплено тестом
`test_chat_egress_reuses_log_channel_sanitizer` (`is`-идентичность функции).
Порядок «маска → вырезание тегов» важен: иначе `sanitize_outgoing` может
разрезать секрет и маска перестанет совпадать. Рубильник
`TELEGRAM_SEND_GUARD_ENABLED` (env-only, дефолт ON) сохраняет
задокументированную семантику «OFF = прямой вызов».

**Телеметрия** — правки не требуется: канал уже безопасен, инвариант заперт
тестами (положительный контроль + не-перередактирование + отбрасывание
слишком длинного значения целиком, а не обрезка «до маски»).

## RED → GREEN

```
база    54546ab5b: 8 failed, 10 passed   (red-base.txt)
кандидат:         18 passed              (green-candidate.txt)
```

RED — ровно 8 чат-тестов (посаженный секрет, ошибка провайдера, `edit_text`,
3 режима rich, обложка, идентичность санитайзера). 10 тестов «уже
безопасно»/«не перередактируем» зелёные и на базе.

## Мутации (обе с байт-точным откатом)

| Мутация | Результат | Откат |
|---|---|---|
| Убрать чат-маску (`sanitize_outgoing(_sanitize_secrets(text))` → `sanitize_outgoing(text)`) | 7 failed (все чат-тесты) | `RESTORED_SHA256=d317eb28…baba92` = PRE, `RESTORE_EXACT=yes` |
| Убрать телеметрическую маску (`_sanitize_str` и JSON-ветка `build_event`) | 2 failed (`test_code_field_masks_planted_secret`, `test_json_payload_masks_planted_secret`) | `RESTORED_SHA256=8a6f67b6…66361f` = PRE, `RESTORE_EXACT=yes` |

## Прогоны (точные числа)

Раунд r0 (кандидат `9b0448db0`, исторический срез):

```
кандидат : 510 passed, 1 failed (suites-candidate.txt)
база     : 502 passed, 9 failed (suites-base.txt)
```

Раунд r1 (текущий кандидат, тот же набор + усиленный страж покрытия):

```
кандидат : 517 passed, 1 failed (suites-candidate-r1.txt)
база     : 504 passed, 11 failed (suites-base-r1.txt)
  падения базы: 8 чат-тестов + 2 resume-теста (F01) + test_every_send_point_...
дельта   : +13 passed = 10 исправленных путей + 3 новых теста стража;
           новых падений нет
```

Отдельно: `test_mod_acl_ux_01_s4_172_egress.py` — 22 passed
(`green-candidate-r1.txt`); `test_outgoing_guard_round1022.py` — кандидат
27 passed / 1 failed (`guard-candidate-r1.txt`), база 24 passed / 1 failed
(`guard-base-r1.txt`).

Состав: новый файл + `test_outgoing_guard_round1022`, `test_log_ring`,
`test_mod_acl_ux_01_m1c_prompt_text_invariant`, `test_mod_acl_ux_01_m1c_prompt_chat_acl`,
`test_mca13_event_contract_round1027`, `test_summary_cover_round1023`,
`test_hotfix3_summary_fallback_round1025`, `test_checkup_contract`,
`test_mca17a_observability_core_round1027`, `test_mca17c_oversight_api_round1047`,
`test_anticliche_round1023`, `test_prompt_readback`.

Единственный остаточный провал **идентичен на базе**:
`test_outgoing_guard_round1022::test_every_send_point_is_registered_or_allowlisted`
— незарегистрированная send-точка `handlers/meme_command.py`
(предсуществующая, вне write scope этой строки: `handlers/**`).

## Контроли в тестах

* позитивный: посаженный секрет (`PLANTED_SECRET`) и формы ошибки провайдера
  (Bearer / `sk-` / креды в URI) обязаны исчезнуть;
* чувствительность: `sk-`, `sk-abc`, «bearer» без токена, `key=` без значения
  не маскируются (`test_near_miss_tokens_are_not_masked`);
* не-перередактирование: обычный ответ (chat id, user id, таймзона, URL с
  query, путь к файлу) проходит байт-в-байт
  (`test_ordinary_message_passes_through_unchanged`,
  `test_ordinary_fields_unchanged`), `keys.llm_api_key` рендерится как
  `configured••••last4`.

## Честные пределы

1. Живая доставка в Telegram не проверялась: нужен реальный бот-сеанс и чат;
   проверена граница `bot.send_message`/`edit_text`/`send_rich_message`
   (fake-bot), то есть фактический payload, который уходит в Bot API.
2. Allowlist-точки (`SEND_ALLOWLIST`) минуют chokepoint по построению; они
   проверены как «нет источника значения настройки» (статические фразы, байты
   медиа, админ-канон), кроме `/debug_config` и `handlers/youtube.py`, где
   маскировка уже есть и заперта тестом/source proof. F01 показал цену такого
   исключения: allowlist глушил модуль целиком, и голый send внутри него был
   невидим. Теперь `SEND_ALLOWLIST_NO_BARE_SENDS` требует от
   `services/direct_chat_service.py` нуля прямых примитивов; остальные
   allowlist-модули (`handlers/meme_command.py`, `handlers/prompt_readback.py`)
   остаются backlog-пунктом F02 ревью — у них нет источника settings/env.
3. `log_ring.sanitize` маскирует значения секретов каталога + форменные
   паттерны (Bearer/Basic, префиксные ключи, URI-креды). Произвольный
   случайный 40-символьный токен, отсутствующий в каталоге и не похожий на
   известный шаблон, не ловится — это ровно тот же класс, что и у лог-канала,
   и требует LLM-суждения о «секретности», поэтому не реализуется.
4. `services/agentic_events` структурно пропускает идентификатороподобные
   значения (≤64 символов); ни один из 62 вызывающих не передаёт туда
   значение settings/env, но собственной маски-вызова там нет — потенциальный
   риск для будущего вызывающего, не текущий дефект.
5. Строка MAC-S4-172 закрывается только по каналу egress (чат+телеметрия);
   лог-канал и API-ответы остаются запертыми M1-B/M1-C (не переоткрывались).
