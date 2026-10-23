# SOUL-1 OFF parity: delta proof (2.58.116)

Reference artifact re-recorded with the SAME stand as the test:
`tests/test_soul1_composer_parity_off.py` (offline, PG down, no
Telegram/LLM/DB). Old baseline came from ASAP 2 canons (5ad73933,
FACTORY_SET `24ae494ac422`); active line is 2.58.114+ (R3 §3.7
`af7de4e9` + R3B `a8d047a7`, FACTORY_SET `0163a686c401`).

## Arithmetic

| section | old chars | new chars | Δ | old sha | new sha | change |
|---|---|---|---|---|---|---|
| P1 | 3225 | 3479 | +254 | `1d4c51c39147` | `22894e57203b` | insert R3B L2 history-boundary instruction (+254 chars) after §3.1 «КАК ПИСАТЬ» |
| P2 | 3073 | 3327 | +254 | `d7281532954d` | `b3c71e14e2a4` | insert R3B L2 history-boundary instruction (+254 chars) after §3.1 «КАК ПИСАТЬ» |
| P3 | 1324 | 1324 | +0 | `a0bf8aba9cd2` | `a0bf8aba9cd2` | unchanged: R3/R3B do not touch this canon |
| P5a | 1107 | 1107 | +0 | `6bae7eb26bc3` | `6bae7eb26bc3` | unchanged: R3/R3B do not touch this canon |
| P5b | 3225 | 3479 | +254 | `1d4c51c39147` | `22894e57203b` | insert R3B L2 history-boundary instruction (+254 chars) after §3.1 «КАК ПИСАТЬ» |
| P4 | 6542 | 8261 | +1719 | `c987c03e3ee0` | `6c2ddc17c998` | §3.7 participation W1->R3 (1533 -> 2682 chars) + R3B continuation (+570 chars after §4.1 contract) |

Total SYSTEM chars: 18496 -> 20977 (+2481). USER payloads: byte-identical in all sections.

Canon constants doing the surgery (bytes from `services/chat_prompts.py`):

- `_DIRECT_L1_PARTICIPATION_W1` = 1533 chars `2d37e32c6847`
- `_DIRECT_L1_PARTICIPATION_R3` = 2682 chars `086f2e1f189d`
- `_DIRECT_L1_CONTINUATION_R3B` = 570 chars `a6cfb2599a7d`
- `_VERBALIZER_HISTORY_BOUNDARY_R3B` = 252 chars `34181731f726`
- `_VERBALIZER_CLAR_PARAGRAPHS` = 843 chars `818237b34d63`

## Checks

- OK  P1: base replay == old baseline | base 3225/1d4c51c39147 vs before 3225/1d4c51c39147
- OK  P2: base replay == old baseline | base 3073/d7281532954d vs before 3073/d7281532954d
- OK  P3: base replay == old baseline | base 1324/a0bf8aba9cd2 vs before 1324/a0bf8aba9cd2
- OK  P5a: base replay == old baseline | base 1107/6bae7eb26bc3 vs before 1107/6bae7eb26bc3
- OK  P5b: base replay == old baseline | base 3225/1d4c51c39147 vs before 3225/1d4c51c39147
- OK  P4: base replay == old baseline | base 6542/c987c03e3ee0 vs before 6542/c987c03e3ee0
- OK  P1: clar paragraphs present exactly once
- OK  P1: R3B boundary absent before
- OK  P2: clar paragraphs present exactly once
- OK  P2: R3B boundary absent before
- OK  P5b: clar paragraphs present exactly once
- OK  P5b: R3B boundary absent before
- OK  P4: W1 participation block present exactly once
- OK  P4: R3 participation block absent before
- OK  P4: R3B continuation absent before
- OK  P1: after == before + only R3/R3B canon surgery | after 3479/22894e57203b vs expected 3479/22894e57203b
- OK  P1: USER part unchanged
- OK  P2: after == before + only R3/R3B canon surgery | after 3327/b3c71e14e2a4 vs expected 3327/b3c71e14e2a4
- OK  P2: USER part unchanged
- OK  P3: after == before + only R3/R3B canon surgery | after 1324/a0bf8aba9cd2 vs expected 1324/a0bf8aba9cd2
- OK  P3: USER part unchanged
- OK  P5a: after == before + only R3/R3B canon surgery | after 1107/6bae7eb26bc3 vs expected 1107/6bae7eb26bc3
- OK  P5a: USER part unchanged
- OK  P5b: after == before + only R3/R3B canon surgery | after 3479/22894e57203b vs expected 3479/22894e57203b
- OK  P5b: USER part unchanged
- OK  P4: after == before + only R3/R3B canon surgery | after 8261/6c2ddc17c998 vs expected 8261/6c2ddc17c998
- OK  P4: USER part unchanged
- OK  R3 §3.7 block: introduced by af7de4e9 | blame-first=af7de4e9
- OK  R3B continuation: introduced by a8d047a7 | blame-first=a8d047a7
- OK  R3B L2 boundary: introduced by a8d047a7 | blame-first=a8d047a7

## Unified diffs

### P1

```diff
--- P1/before
+++ P1/after
@@ -21,2 +21,4 @@
 
+Если в контексте есть пометка о том, что видна только часть истории разговора, один раз естественно назови это ограничение в самом ответе обычными словами и не выдавай невидимое за известное. Саму пометку не цитируй и служебные обозначения не публикуй.
+
 ВЫХОД
```

### P2

```diff
--- P2/before
+++ P2/after
@@ -21,2 +21,4 @@
 
+Если в контексте есть пометка о том, что видна только часть истории разговора, один раз естественно назови это ограничение в самом ответе обычными словами и не выдавай невидимое за известное. Саму пометку не цитируй и служебные обозначения не публикуй.
+
 ВЫХОД
```

### P3

```diff
(no change)
```

### P5a

```diff
(no change)
```

### P5b

```diff
--- P5b/before
+++ P5b/after
@@ -21,2 +21,4 @@
 
+Если в контексте есть пометка о том, что видна только часть истории разговора, один раз естественно назови это ограничение в самом ответе обычными словами и не выдавай невидимое за известное. Саму пометку не цитируй и служебные обозначения не публикуй.
+
 ВЫХОД
```

### P4

```diff
--- P4/before
+++ P4/after
@@ -24,7 +24,11 @@
 
+Сначала определи содержание своей мысли и её адресата: вся беседа, конкретный участник или конкретное сообщение. Форма доставки следует из этого смысла, а не из порядка сообщений в окне. Если по общей теме у тебя есть содержательная мысль для всех, выбери chat и выскажи её; не прячь такую мысль за молчанием из осторожности. Молчание уместно, когда добавить действительно нечего.
+
 Если выбрано текстовое сообщение и этот вызов относится к инициативе, отдельно выбери доставку:
-- chat: обычное сообщение в беседу без reply-привязки. Используй для реакции на общую тему, нескольких участников или развития обсуждения целиком.
-- reply: ответ на конкретное сообщение из предоставленного окна. Используй, только если твоя мысль смыслово относится именно к этому сообщению.
+- chat: обычное сообщение в беседу без reply-привязки. Используй, когда мысль обращена ко всей беседе, к нескольким участникам, продолжает обсуждение целиком, вводит новую тему или является общим замечанием. Упоминание участника по имени не требует reply.
+- reply: ответ на конкретное сообщение из предоставленного окна. Используй, только если твоя мысль отвечает именно на это сообщение и ты можешь назвать его автора и то, на что отвечаешь.
 
-Reply возможен, но никогда не обязателен и не используется как fallback по умолчанию. Для reply укажи конкретный target_message_id из текущего окна. Участника можно упомянуть в обычном сообщении: target_user_id не превращает chat в reply. Если нет подходящего сообщения, выбирай chat либо другое действие, а не произвольную цель. Для реакции не назначай цель reply текстового сообщения. Для молчания не заполняй поля доставки и адресата.
+action=reply означает решение написать текст, а не Telegram-reply: сама по себе эта форма не включает привязку к сообщению.
+
+Reply возможен, но никогда не обязателен и не используется как fallback по умолчанию. Для reply укажи конкретный target_message_id из текущего окна. Если текст обращён к участнику, target_message_id должен быть сообщением этого участника, а target_user_id - его идентификатором из окна; если такого сообщения нет, выбирай chat с упоминанием участника либо другое действие. target_user_id указывай только для реального адресата из окна; при обращении ко всей беседе оставь null. Участника можно упомянуть в обычном сообщении: target_user_id не превращает chat в reply. Если нет подходящего сообщения, выбирай chat либо другое действие, а не произвольную цель. Свежесть сообщения сама по себе не делает его адресатом: цель определяется смыслом твоего текста. Для реакции укажи target_message_id сообщения, на которое ставится реакция; без конкретной цели реакция не исполняется. Для молчания не заполняй поля доставки и адресата.
 
@@ -55,2 +59,3 @@
 Естественные вопросы в обычном живом разговоре, юмор и инициативное участие не являются техническим needs_clarification и не запрещаются.
+Если твоя предыдущая реплика в этой переписке была уточняющим вопросом, а текущее сообщение человека является ответом на него, считай недостающий предмет названным, даже когда ответ короткий и не повторяет исходную просьбу своими словами. Применяй его к исходной задаче и выполняй её; не задавай тот же вопрос снова и не переспрашивай о том же предмете другими словами. Уточнение по одному и тому же намерению задаётся один раз: повторное уточнение допустимо только при новой, ранее не выясненной неизбежной неизвестности, а не для подтверждения уже полученного ответа.
 
```

