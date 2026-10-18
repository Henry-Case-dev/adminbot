# AGENT-CHECKS-2 (window-2) — агентские живые проверки остатков SOUL-1/CFG-01

Окно: **2026-10-18 08:34–08:53 UTC** (+2 коротких read-only recon ~08:54–09:00 UTC).
Прод: **2.58.89**, HEAD `d59fab944bcb3eb0f5d3fa69101d8488da1c155b`
(оба прогонных сеанса: `HEAD=d59fab94…`, `git diff` пуст — 0 правок трекнутых
файлов, `healthz {"status":"ok","version":"2.58.89"}`, `MainPID=3359708`,
`NRestarts=0` до/после).

Вход: бриф лида (остатки по `review-agent-checks-window1.md` §8 и
`plans/owner_questions.md` §3/§6). Карты и `owner_questions.md` не менялись —
закрытие леджером.

## 0. Метод и безопасность

- Синтетические чаты `-1009900000201` (A) и `-1009900000202` (B); профилей
  владельца (5885953495 / -1004482340693 / -1002661910336) не касались.
- Глобальные лимиты: правка 10→2 и возврат 10 — только через штатный
  `POST /api/config` (без X-Chat-Id); возврат подтверждён витриной API.
- Стилевой документ (глобальный): включение одного правила-пресета
  `trailing_period.hard.strip` через `POST /api/speech/style` на секунды и
  мгновенный откат исходным содержимым (revision 6→7→8, rules=0/soft=0).
- **Реальная доставка: в синтетический чат невозможна физически**
  (`getChat(-1009900000201)` → `TelegramBadRequest`); для положительного
  «sent» использован реальный чат бота — ЛС владельца (виден только ему),
  отправка silent, **сообщение сразу удалено** (`delete_message` → ok,
  mid=195). Это вынужденная адаптация буквы брифа (сам чат недостижим);
  настройки владельца не менялись.
- Платные вызовы провайдера: **3** минимальные генерации за окно
  (run1: L1-генерация с харнесс-дефектом редиректа, L3-send-fail; run2:
  L1-генерация с успешной доставкой). Бюджет до/после в `state-pre-post`:
  global 4→7 (лимит 200), chat:A 1→4 (лимит 60). Квота/ключ симуляций —
  бесплатны (0 вызовов провайдера).
- SSH-коннекты: 3 прогонных сеанса (один прерван харнесс-дефектом на
  PRE-STATE, прод не затронут) + 2 коротких read-only recon (журнал,
  git-статус). Все — одиночные успешные логины, без ретраев и перебора;
  креды не печатались (скан evidence — чисто, только эхо sudo-приглашения).
- Привязка: `hash-bind-25889.txt` — 13/13 sha256(12) файлов прод-дерева ==
  блобам релизного `d59fab94` (обе сессии); sha256 файла пробы сессии #3 ==
  sha256(`scripts/agent_checks_w2_probe.py`).

## 1. CFG-01.AC1 (глобальный burst 10→2, третий запрос, возврат без рестарта) — **готово к VERIFIED (леджеру)**

| # | Проверка | Факт (сырой лог: `probe-run1-raw.txt`) |
|---|---|---|
| G0 | до: глобальный слой | `GET /api/config` → burst=10, cooldown=300 |
| G1 | запись 10→2 штатным API | `POST /api/config` (no X-Chat-Id) → 200, `updated=['limits.chat_burst_limit']` |
| G2 | эффективный резолв | витрина value=2; resolve `(burst=2 cooldown=300.0 source='global')` |
| G3 | два запроса израсходовали заряд | allow×2 = 0.0/0.0, слот `burst_left` 2→1→0 (та же точка `allow`, что в `_handle_turn`) |
| G4 | **третий запрос реально ограничен** (полный `_handle_turn`) | фраза `дай передохнуть от твоей духоты, вернусь через 5 мин`, elapsed 0.0s, без платных стадий |
| G5 | остаток фактический | хвост `300s` == расчёт по слоту (`delta=0.0s`), «технически не могу» нет |
| G6/G7 | просмотрщик/событие | `GET /api/status/logs?component=direct_chat` → matched=2; `usage_json={"remaining_seconds":300.0,"burst_limit":2,"cooldown_seconds":300.0,"source":"global"}` |
| G8/G9 | возврат 10 **без рестарта** | `POST /api/config` → 200; resolve `(10, 300.0, 'global')`; 2 заряда + **третий снова допущен** (поведение вернулось) |
| G10 | глобальный слой как был | burst=10, cooldown=300; `NRestarts=0` (процесс не перезапускался) |

## 2. CFG-01.AC2 (override одному чату, другой — по global) — **готово к VERIFIED (леджеру)**

| # | Проверка | Факт (сырой лог: `probe-run1-raw.txt`) |
|---|---|---|
| H0 | чат-B до правок | value=10, `chat_source=''` (наследует global) |
| H1 | override чата-A штатным API | 200, `updated=[burst,cooldown]` (burst=2/cooldown=180) |
| H2 | резолв чата-A | `(2, 180.0, 'chat')` |
| H3 | **чат-B при активном override A** | `(10, 300.0, 'global')` — утечки нет |
| H4 | поведение A | allow×2 ок → третий **ограничен** (остаток 179.99s) |
| H5 | поведение B | allow×2 ок → третий **допущен** (по global) |
| H6/H7 | restore | overrides_A={}, резолв A снова `(10,300,'global')`; профиля B не создавалось (0 строк) |

## 3. SOUL-AMD.8.3 (эффект включённого правила стиля) — **готово к VERIFIED (леджеру); fallback-часть — частично**

`probe-run2-closing-raw.txt` (S-фаза, 28/28):

| # | Проверка | Факт |
|---|---|---|
| S1 | try ДО правила | текст не изменён (`repaired=0`) |
| S2 | включённое правило (пресет trailing_period) через API | 200, applied=true, revision 6→7, rules=0→1, id=`trailing_period.hard.strip` |
| S3 | **следующая сборка отражает правило** | `style_text_masked` = текст **без завершающей точки** (было `…исчезнуть.`, стало `…исчезнуть`) |
| S4 | ревизия видна try | `c6.84cad658cf40` → `c7.e1a301d5414e` |
| S5–S7 | мгновенный откат | restore → revision=8; rules=0/soft=0, правила-пробы нет; try снова не меняет текст |
| S8 | fallback-a (невалидное правило) | `validate_document` даёт явный issue `rule_kind_unknown:no_such_kind`, правило отброшено (не «протекает» и не молчит) |
| S9 | fallback-b (композер без W3-модуля) | фолбэк-ref строится ТОЛЬКО из реального документа (hint=`` при rules=0/soft=0; source='global'); никакого скрытого персонажа |

Остаток (честно): «Core-половина» AMD.8.3 (редактирование Core → следующая
генерация) и полный fallback во всех путях (Summary/Factcheck/Writer) требуют
реальных LLM-генераций — не воспроизводились в этом окне; доля агентской
проверки = живой эффект Style Policy + детерминированные fallback-проверки.

## 4. SOUL-AMD.8.10 (+8.8-OFF) — витрина и L1 отражают per-chat OFF — **готово**

`probe-run2-closing-raw.txt` (I-фаза):

- I1/I2: per-chat OFF через API → capability `disabled/module_disabled`.
- I3/I4 (витрина): `GET /api/speech/capabilities` и `/speech/overview`
  отдают `image_generation: disabled/module_disabled` (+`summary.disabled=1`).
- I5 (L1): `_l1_capability_consistency` реальным методом →
  блок `<capability_notice status="disabled" capability="image_generation">`,
  `denied=('image_generation',)`, генерации нет.
- I6 (отказ): реальный `_image_capability_gate` → текст РОВНО из шаблона
  `message.image_failure.disabled` («Рисовать я сейчас не могу…»), 0 платных.
- I7/I8 (возврат штатным путём): `DELETE /api/config/chat/flags...` → 200;
  витрина снова `ready` после TTL реестра (60 с — документированный контракт).

## 5. SOUL-AMD.8.7 (одно уместное уточнение) — **готово**

- J0: классификатор — `сделай это` → `create_image/ambiguous/create_verb_without_object`.
- J1: реальный гейт → ровно 1 сообщение, текст РОВНО шаблона реестра
  «Уточни: картинку изобразить или текстом обойтись?», 0 платных вызовов.

## 6. SOUL-AMD.8.8 (правдивые отказы) — **готово для 3 условий (OFF/нет ключа/квота)**

| Условие | Статус capability | Текст отказа (== шаблон реестра) |
|---|---|---|
| OFF (per-chat) | `disabled/module_disabled` | «Рисовать я сейчас не могу: генерацию картинок в этом чате выключили…» |
| нет ключа | `not_configured/detail=key_absent` | «Картинку бы изобразил, но генератор не подключён — доступа к провайдеру нет. Это вопрос к хозяину бота…» |
| квота исчерпана | `quota_exhausted/financial_limit_reached` (used=4 ≥ limit=4, реальная бухгалтерия) | «На сегодня картинки закончились: суточный лимит выбран. Не жадность, а квота — обнулится с новым днём…» |

Все три: `handled=True`, 0 вызовов провайдера, «я вообще не умею» отсутствует,
тексты РАЗНЫЕ. Нет-ключ симулирован per-chat override `keys.image_api_key=""`
(сервисное письмо; каталог не позволяет переносить ключи на чат by design);
**глобальный ключ не изменялся**, override снят. Провайдер-«временно не
отвечает» — остаток: требует реального транзиентного сбоя (не форсировали,
в окне-1 покрыт мок-исходом).

## 7. SOUL-AMD.5.17 / AMD.8.6 (реальная доставка, один вызов на намерение) — **готово**

- L1 (run2, 28/28): реальный вход `_image_pre_gate_block` (тот же, что в
  `_handle_turn`) → **ровно 1 вызов провайдера**, реальная отправка
  `bot.send_photo` в Telegram: `ok=true, message_id=195, bytes=1545484`;
  блок `<image_result status="ok" delivery="sent">`; журнал
  `[image] sent … delivery_failed=False`; сообщение сразу удалено
  (`L1_delete`, mid=195). Резерв `990000811` → committed, delivery_failed=False.
- L2 (повтор того же хода): `delivery="already"`, 0 новых вызовов провайдера,
  0 повторных отправок (идемпотентность).
- L4: журнал резервов содержит и committed-ok, и committed-delivery_failed —
  единый механизм доставки/квоты.

## 8. SOUL-AMD.8.9 (send-fail) — **готово (реальная ошибка Telegram)**

- run1: L3 — реальный send в недостижимый синтетический чат →
  `TelegramBadRequest: chat not found`; блок
  `<image_result status="error" reason="delivery_failed">` + «Ничего не
  отправлено», «sent» не заявляется; резерв `990000808` → committed,
  `delivery_failed=True`. Реальной генерации платили 1 раз, без авто-повтора.

## 9. SOUL-AMD.8.11 (поиск/фактчек/видео) — **остаток подтверждён**

- Видео: capability `video_summary = not_configured / media_source_unconfigured /
  cobalt_absent` (оба прогона). Сценарий без медиа-источника невыполним —
  принятый остаток (как в окне-1). Поиск/фактчек закрыты окном-1.

## 10. Девиации лейна (харнесс, не продукт)

1. Сессия #1 (08:34) прервана на PRE-STATE: в state-скрипте фигурировала
   несуществующая колонка `worker_budget."limit"` → процесс state-скрипта
   завис на выходе; проба **не запускалась**, прод не затронут (только
   read-only). Исправлено (колонки по факту схемы + гарантированный выход).
2. run1/L1: RecordingBot перенаправлял send на другой чат, но передавал
   `reply_to_message_id` синтетического чата → Telegram отклонил
   (`message to be replied not found`) → это отличалось от ожидаемого «sent».
   Исправлено (при редиректе reply-таргет снимается); перепрогнана только
   L1-фаза (run2) — успешная реальная доставка.
3. run1/S3: ассерт искал поле `changed` в `style_pass` — такого поля в
   `as_dict()` нет; факт эффекта уже был виден по тексту. Исправлено
   (`repaired`/`text_sha12`/точное сравнение).
4. run1/I6,J1,K1,K2: полный `_handle_turn` в пробе падает в
   `_build_user_content` (`memory=None`) ДО image-гейта — известное
   ограничение харнесса окна-1 (там это тоже дефект-класс). Отказные тексты
   проверены вызовом реального `_image_capability_gate` — тем же методом, что
   зовёт `_handle_turn` (паттерн, принятый ревьюером в окне-1).
5. журнальный сниппет в run1/run2: `grep -E` без `--` принял `-1009…` за
   опцию (диагностический сниппет пуст; счётчики и классификация добраны
   отдельным read-only recon — `recon-journal-tracebacks.txt`).
6. В логах сеансов печаталось `TRACKED_MOD=13` — это `git status --porcelain`
   вместе с untracked; фактических правок трекнутых файлов **0**
   (`recon-git-binding.txt`: `git diff --stat/--name-only` пусты; 13 записей —
   старые .bak/pre_migration_backup).

## 11. Incidental finding (НЕ этого лейна; pre-existing)

В журнале бота **до** наших прогонов (08:02:21 и 08:09:49 UTC) два Traceback:
`[style_policy] document save failed` и `[speech] expression chat write failed`
— оба: `services.chat_lore_store.ChatLorePgUnavailable: PostgreSQL недоступен
(пул отсутствует)` из `chat_params.set_chat_params`, вызванного БЕЗ `pg`
(`web/api/speech.py:2184` `_write_expression`; чат-ветка
`style_policy.save_policy_document` → `set_root` без pg). Т.е. **сохранение
«Стиль письма»/«Выражение» для КОНКРЕТНОГО чата через MiniApp падает**
(глобальный путь работает). Пишу как находку для отдельного разбора: может
задевать формулировку AMD.8.3 «во всех соответствующих путях» (per-chat
части). В моём окне глобальные пути подтверждены; лейн ничего не чинил
(вне write-scope). Evidence: `recon-journal-tracebacks.txt`; код:
`web/api/speech.py:2184`, `services/style_policy.py:2272`.

## 12. Гигиена окна

- Журнал бота за окно: **ERROR=0, CRITICAL=0**; Traceback=2 — оба из п.11
  (до окна, не наши); `[tma-auth] valid=True`=150; healthz 2.58.89.
- `MainPID=3359708`, `NRestarts=0` — прод-процесс не перезапускался (hot-путь).
- /tmp очищен (`CLEANED=1`); секрет-скан evidence — чисто; крeды/ключи не
  печатались (в логах только эхо `[sudo] password for nik:`).

## 13. Синтетические следы (сознательно, как evidence)

| Артефакт | Значение | Почему оставлено |
|---|---|---|
| `mca_events` (SQLite) `direct_chat_throttle` | chat=A, source=global burst=2 | доказательство AC1 (вьюер) |
| `image_reservation` (PG) | 990000807 (delivery_failed), 990000808 (send-fail), 990000811 (успешная доставка) | доказательства AMD.5.17/8.9 |
| `bot_settings style.policy` | содержимое как было (rules=0/soft=0), revision=8 | штатная ревизионная модель (окно-1 уже приняла 2→4) |

Снято: профили A/B, overrides, строки `throttle_state` (все scope) — по нулям
до/после.

## 14. Строки для леджера (кратко)

| Строка | Вердикт | Остаток |
|---|---|---|
| CFG-01.AC1 | готово к VERIFIED | нет |
| CFG-01.AC2 | готово к VERIFIED | нет |
| SOUL-AMD.8.3 | готово к VERIFIED (Style-эффект + fallback-проверки) | Core-половина и полный fallback LLM-путей — вне окна (реальные генерации не форсировались) |
| SOUL-AMD.8.10 | готово к VERIFIED | смена провайдера (не форсировалась) |
| SOUL-AMD.8.7 | готово к VERIFIED | нет |
| SOUL-AMD.8.8 | готово (OFF/нет ключа/квота живые, тексты разные/правдивые) | «провайдер временно не отвечает» — мок-остаток |
| SOUL-AMD.5.17 / 8.6 | готово к VERIFIED | нет (реальная доставка + идемпотентность) |
| SOUL-AMD.8.9 | готово к VERIFIED | нет (реальный send-fail) |
| SOUL-AMD.8.11 (видео) | остаток подтверждён | not_configured (cobalt_absent) — невоспроизводимо без медиа-источника |

## 15. Файлы evidence

| Файл | Содержимое |
|---|---|
| `probe-run1-raw.txt` | сессия #2 (фазы ALL): PRE/POST-state, сырой вывод пробы (G/H/S/L/K/M), журнал, systemctl |
| `probe-run2-closing-raw.txt` | сессия #3 (фазы S,I,J,L,K; `ok=28/28`): закрытие остатков |
| `hash-bind-25889.txt` | привязка: 13/13 sha12 файлов == d59fab94; sha256 пробы |
| `state-pre-post-25889.txt` | сводка PRE/POST-состояний обоих прогонов |
| `recon-journal-tracebacks.txt` | read-only журнал: классификация Traceback'ов (incidental finding) |
| `recon-git-binding.txt` | read-only git-статус прод-дерева (0 трекнутых правок) |
| `scripts/` | прод-проба (финальная), state-скрипт, раннер, recon-скрипты, локальный предпрогон |
| `verdicts.json` | машинный список строк↔вердиктов для леджера |
| `SHA256SUMS.txt` | sha256 всех артефактов этого каталога |
