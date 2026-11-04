# BGS-03/04 — evidence snapshot (builder lane `bgs/speech-guards`)

- Base: `905ba7ab` (evol/impl). Lane branch: `bgs/speech-guards`.
- Candidates: `c8fb19d8` (implementation + tests), `e0527a6b` (G3 test fix),
  `416c7d86` (direct plain-table contract; финальный кандидат полосы).
- Source: `plans/owner_inputs/2026-11-05-behavior-gates-simplification.md`
  §4 (BGS-03), §5 (BGS-04), §8 (UR-15), §9 (acceptance).

## Что изменено

| Файл | Суть |
|---|---|
| `services/public_speech_guard.py` | `guard_public_text` — только наблюдение: текст возвращается байт-в-байт, находки идут в `findings` + событие `speech_observation` (`component=public_speech_guard`, `stage=<seam>`, `usage_json.codes`). Удалены срез-регэкспы (`_strip_matches`, `_token_cut_re`, `_bracket_block_re`, `_INVERSE_STRIP_RE`, `MachineArtifact.strip`). `metatext_retry_reason` всегда `None`. `GuardResult.changed` всегда `False`. |
| `services/negative_constraints.py` | Повтор остаётся только при реальной трансформации: form-гарды G1–G3 (`form_contract`) и numeric внутри неё. Формат/метатекст/клише — наблюдение (`format_observed`, `metatext_observed`, `cliche_observed`); `format_retry_system_prompt` и `FORMAT_RETRY_REASON`-ветка удалены; `_MAX_RETRIES_HARD_CAP=2` сохранён. Свободная генерация: numeric-повтор не запускается, остаётся детерминированная правка. |
| `services/outgoing_guard.py` | Без изменений (технические маркеры `<thought>`, `fact:ID`, `msg:ID`, target — узкий идемпотентный санитайзер). |
| `services/style_policy.py` | Без изменений: единый проход `apply_style_policy` (extent → правила формы → антизалипание), защищённые спаны `segment/protected_ranges`, `_collapse_quotes_rules` не даёт двух правил кавычек. |
| `services/prompt_composer.py` | Без изменений: машинных директив, требующих удалённых блокировок, в композере нет (retry-каноны живут в `prompt_style_blocks`/`prompt_registry`, теперь недостижимы и сохранены как версии промптов). |

## Тесты

- `tests/test_bgs0304_speech_observation.py` (новый, 24 теста):
  байт-в-байт для «по моим наблюдениям», «я нейросеть», «мои промпты»,
  «сейчас пошучу» и их цитат; `<thought>`/`fact:123` по-прежнему
  вычищаются техническим санитайзером; ложное совпадение не даёт пустого
  сообщения; отсутствие лишней генерации на стиль/формат/метатекст;
  form-контракт ловит число/отрицание/чужое имя; владельческие правила
  (no_emoji/no_quotes/trailing_period) применяются один раз; защищённые
  спаны (URL, код) и дословные цитаты не искажаются.
- Переписаны под новый контракт: `test_cfg07_guard_07d5.py`,
  `test_cfg07_guard_tail.py`, `test_negative_constraints_round1022.py`,
  `test_mca15_chat_statistics_round1028.py`,
  `test_verbilizer_response_modes_round1023.py`.

## Прогоны (код `416c7d86`, docs `db62d8e6`)

- Сводный прогон полосы (bgs0304 + cfg07_guard_07d5 + cfg07_guard_tail +
  mca15_chat_statistics + negative_constraints_round1022 +
  direct_two_call_round1022 + direct_chat + direct_chat_prompts +
  rc_direct_self_correction + soul1_style_policy + outgoing_guard_round1022)
  → **578 passed, 1 failed**; единственный failed —
  `test_every_send_point_is_registered_or_allowlisted`:
  `handlers/meme_command.py` отсутствует в `SEND_POINTS`/allowlist. Файл есть
  и на базе `905ba7ab` (чужая полоса meme-autodelete), к BGS-03/04 не относится.
- `test_bgs0304_speech_observation` → 24 passed.
- `test_bgs0304 + cfg07_guard_07d5 + cfg07_guard_tail +
  mca15_chat_statistics + negative_constraints_round1022` → 245 passed.
- Прямой чат: `test_direct_two_call_round1022 + test_direct_chat +
  test_direct_chat_prompts + rc_direct_self_correction` → 250 passed.
- `test_soul1_style_policy + outgoing_guard_round1022` → 83 passed, 1 failed:
  `test_every_send_point_is_registered_or_allowlisted` —
  `handlers/meme_command.py` не в `SEND_POINTS`/allowlist (файл существует и на
  базе `905ba7ab`; чужая полоса meme-autodelete, к BGS-03/04 не относится).
- `test_cfg07_egress_dictionary + cfg07_backstage_contract + cfg07a_f1` →
  200 passed (сохранено с предыдущего кандидата, файлы полосы не менялись).
- `test_mca08_style_form` → 82 passed, 1 failed:
  `test_declared_events_really_emitted_in_code` (`mca07_answer_cache` объявлен,
  но не эмитится в коде) — пре-существующее, вне диффа.
- `test_verbilizer_response_modes_round1023` → 70 passed, 1 failed, 2 errors:
  `test_summary_kill_switch_off_prev_narrator` (в собранном промпте ожидаемо нет
  блока `<Speech_Base>`) и 2 ERROR параметризации
  `test_no_bullet_ban_in_deep_research` (`ValueError: the environment variable is
  longer than 32767 characters` — id параметра содержит переводы строк).
  Проверено на чистом worktree базы `905ba7ab`: те же 1 failed + 2 errors.

## Мутации (доказательство, что тесты способны падать; кандидат `416c7d86`)

- M1 «вернуть вырезание фраз словаря» в `guard_public_text` (regex-срез по
  `findings`) → RED: 9 failed, 15 passed в `test_bgs0304_speech_observation`
  (все параметры живых фраз, цитаты и `test_false_match_never_empties_message`).
- M2 «вернуть reroll по кодам клише/формата» в `verbalize_validated`
  (ветка `CLICHE_RETRY_SYSTEM_PROMPT` + выход из раннего возврата) → RED:
  3 failed, 21 passed (стиль, таблица, плюс проверка bounded-формы).
- После мутаций файлы восстановлены `git checkout --`, дерево чистое,
  повторный прогон `test_bgs0304` → 24 passed.

## Conflict Resolution Matrix (BGS-03/BGS-04)

| Прежний пункт | Что было | Решение сейчас | Доказательство |
|---|---|---|---|
| `UNIFIED-REPLY` UR-15 (Form/Numeric/Format retry в общем Writer) | обязательный повтор на форму/числа/формат | **уточнено BGS-04:** повтор только при реальной трансформации (`form_contract` Stage-1→Stage-2) и для numeric внутри неё; свободный L2/Initiative не перегенерируется; формат — наблюдение | `test_no_extra_generation_for_style_or_format`, `test_transform_path_keeps_facts_and_stays_bounded`, `test_plain_table_delivered_without_third_call`, `test_table_in_plain_observed_not_regenerated` |
| CFG-07D.5 metatext retry | `metatext_reason` → повтор + вырезание формул | **снято:** код пишется в `stats['metatext_observed']`, текст байт-в-байт, LLM не вызывается | `test_no_extra_generation_for_metatext`, `test_natural_phrase_passthrough_byte_identical` |
| BGS-03 §1–2 public speech guard | срез/блокировка живого ответа по `_BACKSTAGE_FAMILIES`, `claims_total_verification`, `find_semantic_metatext` | **observability-only:** `GuardResult.text` = исходный, `findings` + событие `speech_observation` | `test_natural_phrase_passthrough_byte_identical`, `test_observation_codes_are_not_private_text` |
| BGS-03 §3 техническая очистка | `sanitize_outgoing` | **сохранено без расширения:** `<thought>`, `fact:ID`, `msg:ID`, target-маркер; узко и идемпотентно | `test_real_machine_markers_are_still_stripped`, `test_speech_guard_does_not_touch_live_words_in_technical_cleanup` |
| Формат доставки `plain_no_tables`/`bullet_list` | независимый guard с повтором `format_retry` | **наблюдение** `stats['format_observed']`; Telegram принимает обычный текст | `test_table_in_plain_observed_not_regenerated`, `test_plain_table_delivered_without_third_call` |
| Числа/имена/отрицания | veto на свободную генерацию | **сохранено там, где тексту реально меняют:** form-гарды G1–G3 + numeric-правка/повтор внутри трансформации; свободный путь — детерминированная коррекция, текст не пустеет | `test_form_contract_catches_changed_number_negation_and_new_name`, `test_free_path_never_empties_reply_for_number` |
| Правила владельца (`no_emoji`, `no_quotes`, `trailing_period`) | один проход | **без изменений:** `apply_style_policy` один раз, защищённые спаны и дословные цитаты целы | `test_owner_rules_apply_exactly_once`, `test_owner_rules_keep_protected_spans`, `test_verbatim_quote_untouched_by_owner_rules` |
| Anti-Cliché | diagnostic-only | **сохранено:** `stats['cliche_observed']`, `anti_cliche_retries == 0` | `test_no_extra_generation_for_style_or_format` |

## Координация

В рабочем дереве ветки параллельно работал второй писатель (правки
`services/*` и тестов в 06:02–06:09, включая `test_direct_two_call_round1022.py`).
Снимок зафиксирован коммитами `c8fb19d8` и `e0527a6b`, чтобы рестарты не
потеряли работу; дальнейшие правки в тех же файлах требуют одного владельца.
