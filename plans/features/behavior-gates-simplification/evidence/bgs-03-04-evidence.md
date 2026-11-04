# BGS-03/04 — evidence snapshot (builder lane `bgs/speech-guards`)

- Base: `905ba7ab` (evol/impl). Lane branch: `bgs/speech-guards`.
- Candidates: `c8fb19d8` (implementation + tests), `e0527a6b` (G3 test fix).
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

## Прогоны (кандидат `e0527a6b`)

- `test_bgs0304 + cfg07_guard_07d5 + cfg07_guard_tail` → 94 passed.
- `test_cfg07_egress_dictionary + cfg07_backstage_contract + cfg07a_f1 +
  outgoing_guard_round1022` → 200 passed, 1 failed:
  `test_every_send_point_is_registered_or_allowlisted` —
  `handlers/meme_command.py` не в `SEND_POINTS` (чужая полоса meme-autodelete,
  к BGS-03/04 не относится).
- `test_mca08_style_form` (один файл) → 82 passed, 1 failed:
  `test_declared_events_really_emitted_in_code` (`mca07_answer_cache` объявлен,
  но не эмитится в коде) — пре-существующее, вне диффа.
- `test_anticliche_round1023 + quotes_modes + soul1_style_policy` → зелёные;
  в `test_verbilizer_response_modes_round1023` падают
  `test_summary_kill_switch_off_prev_narrator` (утверждение о блоке
  `<Speech_Base>` в собранном промпте) и 2 ERROR параметризации
  `test_no_bullet_ban_in_deep_research` (id содержат переводы строк) —
  оба про композицию промпта, дифф полосы её не касается.

## Мутации (доказательство, что тесты способны падать)

- M1 «вернуть вырезание фраз» в `guard_public_text` → RED: 21 failed.
- M2 «вернуть reroll по клише/кодам» в `verbalize_validate` → RED: 18 failed.
- После мутаций файлы восстановлены из git (`git checkout --`), дерево чистое,
  повторный прогон 94 passed.

## Координация

В рабочем дереве ветки параллельно работал второй писатель (правки
`services/*` и тестов в 06:02–06:09, включая `test_direct_two_call_round1022.py`).
Снимок зафиксирован коммитами `c8fb19d8` и `e0527a6b`, чтобы рестарты не
потеряли работу; дальнейшие правки в тех же файлах требуют одного владельца.
