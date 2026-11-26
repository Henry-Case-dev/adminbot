# MAC-S4-172 (egress) — секрет не уходит ни в чат, ни в телеметрию

Строка MOD-ACL-UX-01: `MAC-S4-172` (вторая половина; первая — лог и
`/api/status/logs` — заперта M1-B/M1-C).
База: `54546ab5b201a5d8bd169bad613e730d371fc3b9` (2.58.253), ветка
`feat/mod-acl-s4-172-egress`.

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

```
кандидат : 510 passed, 1 failed (suites-candidate.txt)
база     : 502 passed, 9 failed (suites-base.txt)
```

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
   маскировка уже есть и заперта тестом/source proof.
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
