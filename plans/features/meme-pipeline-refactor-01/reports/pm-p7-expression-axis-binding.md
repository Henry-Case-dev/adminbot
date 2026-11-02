# P7 `MEME-INITIATIVE-LAYERS` — ось Expression на пути инициативы (привязка PM)

Дата: 03.11.2026. Кандидат привязки: `5fb018ab` (`evol/impl`, merge `5dd0cb36` → `evol/impl`).
Требование: `MEME-INIT-EXPRESSION-PASS` (манифест `OI-2026-11-03-MEME-JOKE-SPEECH-LAYERS`, строка 20 источника).

## Что изменилось в кандидате

`5dd0cb36` = merge `5fb018ab` (`git diff --stat`: 1 файл, +24 / −6) —
`tests/test_initiative_speech_layers_chat_overrides.py`:

* `_configure()` получил параметр `expression_enabled` и пробрасывает его в ОБА
  документа `character.expression` (глобальный и чатовый), т.е. ось выключается
  штатным путём, а не подменой резолвера;
* параметризация `test_initiative_disabled_axis_skips_layer_with_reason`
  расширена третьим случаем `("expression", "expression_disabled", ...)`;
* для случая `expression` дополнительно проверяется, что Core и Style Policy
  продолжают жить: `manifest.versions["style_policy"]` равен чатовой ревизии,
  `chat_policy.hint` в payload, слой `core` и `style_policy_hint` рендерены;
* карта слоёв вынесена в `_AXIS_LAYER`, чтобы имя слоя не вычислялось тернарником.

## Вывод Reviewer (передан координатором, отдельного файла отчёта нет)

Дословно из handoff координатора: «reviewer verified it independently (real
assembled payload, fails if the layer renders, core/style assertions real,
nothing weakened) — commit `5dd0cb36`, merged at `5fb018ab`».

Отдельный отчёт Reviewer по этому случаю **не создавался**; вердикт существует
только как handoff координатора. Чтобы он не остался плавающим утверждением в
чате, он зафиксирован здесь вместе с независимой перепроверкой PM ниже.
Повторного ревью PM не проводил и Reviewer за него не выдаёт.

## Независимая перепроверка PM (этот worktree, 03.11.2026)

Кандидат проверялся при чистом дереве на `5fb018ab` (`git status --porcelain` пуст).

1. `pytest tests/test_initiative_speech_layers_chat_overrides.py -q` → **4 passed**
   (1 кейс чатовых оверрайдов + 3 параметризованных кейса выключенной оси).
2. Проба резолвера (`resolve_expression_settings`): `enabled=False` → `text_len=0`,
   `revision=""`, `skip_reason="expression_disabled"`, `source="chat"`;
   `enabled=True` → 686 символов текста, ревизия `628ee3b58325`, `enabled=True`.
   Значит «выключено» приходит из документа конфигурации, а не из теста.
3. Мутация M1: убрать из композера условие `or not expression.enabled` →
   тест **остаётся зелёным**. Честная граница этой проверки: слой отсутствует и
   причина названа (наблюдаемый контракт), но тест не доказывает, какая из двух
   защит (резолвер/build или композер) сработала. Это не ослабление требования —
   acceptance сформулирован наблюдаемо («при выключенном Expression — честная
   причина пропуска»), и он проверен на реальном payload.
4. Мутация M2: builder `build_expression_settings` игнорирует `enabled` для текста →
   тест **падает** на `assert 'expression_absent' == 'expression_disabled'`,
   т.е. имя причины проверяется содержательно, а не «любая строка».
5. Мутация M3: композер рендерит слой «Выражения» всегда (фиксированный
   mutant-текст) → тест **падает** на `assert target.rendered is False`
   (`LayerTrace(layer='expression', ..., rendered=True)`), плюс падает кейс
   чатовых оверрайдов и кейс выключенного Core; кейс `style` независим.
   Это и есть заявленная Reviewer проверка «fails if the layer renders».
6. Дерево восстановлено `git checkout --`, `git status --porcelain` пуст,
   HEAD = `5fb018ab`.

## Что теперь покрыто по оси Expression

Оба случая `expression_disabled` существуют и оба проверяют наблюдаемое:

* этап прикола: `tests/test_meme_joke_speech_layers.py` (кейс выключенной оси
  «Выражения» в жанровом Writer'е прикола);
* обычная текстовая инициатива: `tests/test_initiative_speech_layers_chat_overrides.py`
  (`[expression-expression_disabled-...]`, кандидат `5fb018ab`).

Плюс общий уровень композера — `tests/test_add_exp_expression.py`.
