# Definition of Done — REMOVE-LEGACY-REPHRASING v2.0 (§10, все пункты обязательны)

- **Источник (дословный):** `plans/owner_inputs/2026-11-05-remove-legacy-rephrasing-v2.md`, §10, строки 239–247 (`source_sha256 = 8dc7751c893704b895b4fcfd8475b504e668294e6966688a278ab6e261bb3f22`).
- **Кандидат:** ветка `evol/impl` @ `df00f178` (merge RLR-09 live-model proof artifacts `47e1e2c3`). Дата: 2026-11-05.
- **Статусы:** `proven` — поведение доказано привязанными свидетельствами; `partially` — доказана часть, остальное перечислено; `not yet` — не выполнено.
- **Рамка честности (R-09.5):** релиз и прод-проверка **не выполнены** — соответствующие пункты остаются `not yet`, строки `R-DOD.9`/`R-PROC.5`/`R-DOD.8` в карте держатся `PENDING`.

## 1. Одна финальная Writer-стадия; tools/evidence до неё; silent/react без L2 — **proven**

- Источник §10.1: «Каждый активный Direct/Initiative `reply` имеет одну финальную логическую Writer-стадию, все tools/evidence до неё; `silent/react` не вызывают L2.»
- Свидетельства: `R-02.1–R-02.5` VERIFIED (0e3f96be, merge b62bc51e) — второго автора нет; `R-08.3` VERIFIED (инициатива silent/react/reply без постперегенерации); `route-matrix.md` — 35 путей с подсчётом независимых финальных авторских генераций (снимок c8d9866e); R-09 live (47e1e2c3): `llm_calls.final = 1` в s1/s2/s3/s4b/s5/s6, tools до Writer'а (s2: `tool=1` до `final=1`).
- Что осталось (clerical): формальные строки `R-01.0–R-01.5`, `R-DEF.MAINRULE/PREP/WRITER` остаются `PENDING` без привязки к кандидату — поведение доказано, привязка выполняется на release-волне. Карта: `R-DOD.1` PENDING.

## 2. Нет достижимого System2 `tool-final → JSON → Verbalizer`; нет скрытого возврата — **proven**

- Источник §10.2: «Нет достижимого System2 `tool-final → JSON → Verbalizer` как второго автора; при сбоях/флагах нет скрытого возврата в него.»
- Свидетельства: `R-02.1–R-02.5` VERIFIED; `R-BND.1`/`R-BND.2` VERIFIED (границы System2); `R-ADM.4` VERIFIED (d49b10ac) — `SYSTEM2_DIRECT_ENABLED` игнорируется для нового маршрута, `false`/`0`/null не активируют двойную архитектуру; route-matrix §1.3: `_synthesize_direct_answer` не существует, `verbalize_validated` — ровно 4 production-точки (machine-contract валидация в фактчеке/саммари/одной точке direct), loops/retries свободной речи отсутствуют; live s4 — честный путь отказа без переключения на legacy.
- Что осталось: только формальная привязка `R-DOD.2` на release-волне.

## 3. Нет post-L2 reroll/drop (form/numeric/metatext/format/evidence/duplicate/freshness/style/cliché) — **partially**

- Источник §10.3: «Нет post-L2 LLM reroll для free-form из-за form/numeric/metatext/format/evidence/duplicate/freshness/style/cliché; нет автоматического смыслового drop/replace.»
- Доказано: `R-04.1` VERIFIED (63085f70/20d19ad0 — свободная перегенерация из-за формы/лексики снята, machine-протокол разделён); мерж c8d9866e «RLR-04 direct-chat postprocessing removals»: numeric-гард = наблюдение (`direct_chat_service.py:5507–5532`, `corrected=False`), egress = наблюдение (BGS-02, `:5533–5568`), duplicate/freshness = наблюдение (`:5579–5606`); `tests/test_rlr_dcs_postprocess.py` (`test_apply_numeric_guard_has_no_product_caller`, `test_no_post_l2_llm_step_in_direct_postprocess_source`); `tests/test_rlr_negative_matrix.py` (8 строк §8, реальные гейты, 74ce5246); R-09 live: `semantic_rewrite_count = 0` во всех сценариях, единственная меняющая op — `owner_style_punctuation`.
- Чего не хватает:
  1. строки `R-04.2–R-04.6`, `R-BAN.CORE…R-BAN.FRESHNESS`, `R-BND.4–R-BND.10` остаются `PENDING` с **устаревшими** `pending_reason` («неслитая часть среза» — не соответствует HEAD после c8d9866e): нужна перепривязка от кандидата c8d9866e к `tests/test_rlr_dcs_postprocess.py`;
  2. UI-часть BGS-04 («применить в активном коде **и UI**») — `R-ADM.1/5/6/7` ждут волну UR-F/PVR.
- Карта: `R-DOD.3` PENDING.

## 4. Честный provider fallback и continuation по length — **proven**

- Источник §10.4: «Честный provider fallback и continuation по length сохранены, не маскируют unfinished outputs.»
- Свидетельства: `R-08.14` VERIFIED (673677a1, merge 8eb6893b; `tests/test_rlr_length_continuation.py` 17 passed: продолжение с префиксом, снятие повтора хвоста, честный отказ без публикации обрезка); R-09 live: s5 — `finish_reason=length` → `continuation=2`, текст заканчивается целым словом/предложением, при заведомо малом лимите — честный `unfinished_answer`; s4 — честный путь отказа (`fallback_statuses=[401,401]` — факт из JSON), s4b — рабочая вторая нога, `provider_retry=2` отдельным классом, финальный автор один.
- Примечание (не блокер кода): 401 на второй ноге — состояние ключа `LLM_FALLBACK_API_KEY` в `.env`, требует внимания владельца/DevOps.
- Карта: `R-DOD.4` PENDING (привязка на release-волне).

## 5. Idempotency Telegram-доставки, спец-продукты, речевые правила, provenance — **partially**

- Источник §10.5: «Idempotency Telegram-доставки, специальные продукты, пользовательские правила речи и source provenance сохранены.»
- Доказано: `R-08.19`/`R-08.20` VERIFIED (отправленная картинка без второго текста; смерть/перезапуск процесса без повторной отправки — 74ce5246/9885b4b5); `R-OBS.5`/`R-OBS.7` VERIFIED (манифест доставочных операций, идемпотентный ключ и Telegram IDs в трассе); `R-CONF.11` VERIFIED (спец-продукты и промпты не тронуты); live: s3 инициатива байт-в-байт, s6 байт-в-байт с сохранением фактов, `owner_style_punctuation` — единственная меняющая op.
- Чего не хватает: строки `R-05.2` (durable idempotency: correlation_id/tg_message_id/reservations/SendRecheck) и `R-06.9` (provenance цитат/чисел/авторства) не привязаны; **живая Telegram-доставка не упражнялась** (транспорт подменён RecordingBot) — проверяется на release/прод (п. 9).
- Карта: `R-DOD.5` PENDING.

## 6. API/админка/конфиги обновлены; нет dead controls; legacy не реактивируется — **partially**

- Источник §10.6: «Обновлены API/админка/конфиги, нет dead controls, старые настройки не реактивируют legacy.»
- Доказано (backend): `R-ADM.2`/`R-ADM.3`/`R-ADM.4` VERIFIED + `R-CONF.11` VERIFIED (d49b10ac, merge a4593936): migration manifest (`removed`/`retained_*`/`deprecated_compat`), скрытие removed/deprecated_compat из редактируемого каталога при сохранении читаемости, нейтрализация `SYSTEM2_DIRECT_ENABLED` при любом сыром значении, честные подписи; `tests/test_rlr_admin_manifest.py` + `tests/test_param_catalog.py` — 61 passed.
- Чего не хватает: UI-часть `R-ADM.1`/`R-ADM.5`/`R-ADM.6`/`R-ADM.7` (диагностика одного ответа, пользовательские формулировки, работоспособность редакторов) — заблокирована волной UR-F/PVR (`blocked_by_upstream`); dead controls в UI до неё не финализированы.
- Карта: `R-DOD.6` PENDING.

## 7. Промпты/история/заводские версии не изменены; память и эмбеддинги не пересозданы — **proven**

- Источник §10.7: «Все сохранённые пользовательские промпты и их история/заводские версии не изменены, память и эмбеддинги не пересозданы.»
- Свидетельства: `R-CONF.11` VERIFIED — `git show --stat d49b10ac` без изменений хранилища промптов/API версий/назначения базовых версий; static: `admin-migration-manifest.md` — тексты ручных промптов, factory baseline и прежние версии не изменяются, DML/миграций данных срез не выполняет; правка код-канона L1 (c010a9fc) — аддитивное поле `preserve_source_facts` с сохранением прежней ревизии EVR4 (`PREV_DIRECT_L1_PLANNER_EVR4`, откат через `prompt_migrations`), тексты владельца Core/Expression/Style байт-в-байт; память/эмбеддинги не пересоздавались (миграций данных нет; live s1 — обычный фоновый memorize/rerank).
- Карта: `R-DOD.7` PENDING (привязка на release-волне).

## 8. Conflict Resolution Matrix + route matrix по актуальной ветке приложены к отчёту — **partially**

- Источник §10.8: «Conflict Resolution Matrix + route matrix по актуальной ветке приложены к человеческому отчёту.»
- Доказано: `conflict-resolution-matrix.md` создан на df00f178 (точные ссылки на UR-15, BGS-04, BGS-04.10, UR-06–08/BGS-01, BGS-02/03, BGS-05/06, PVR-FC, PVR, Speech/Character; `R-CONF.13` → VERIFIED); `route-matrix.md` существует (35 путей, метод import graph + call sites + гейты, прогон 57 passed).
- Чего не хватает:
  1. route-matrix снят на c8d9866e — **до** мержей RLR-03.3 (598ff965, c010a9fc: проводка узкой проверки защищённых фактов + поле `preserve_source_facts`), RLR-08.14 (1b82db2b, 673677a1: новая стадия `l2_continuation`, правки `llm_client`) и RLR-06 (turn_trace — на авторство не влияет). Нужно точечное переснятие затронутых зон: явная трансформация и length-continuation;
  2. «приложены к человеческому отчёту» — отчёт создаётся на release-волне.
- Карта: `R-DOD.8` PENDING (`pending_reason` обновлён).

## 9. Reviewer подтвердил call graph и payload; DevOps — релиз и прод-проверка; итог в durable state — **not yet**

- Источник §10.9: «Независимый Reviewer подтвердил реальный call graph и выходные payload; DevOps выполнил релиз и прод-проверку; итог записан в durable state.»
- Что уже есть (частично): срезовые приёмки Reviewer — RLR-02 (0e3f96be/b62bc51e), RLR-03 (63085f70/20d19ad0, 93e64dc8/b9bd717b, c39e371d/15e8bcc3), RLR-05-backend (d49b10ac/a4593936), RLR-06 (b3303d39/71c3d95a), acceptance-rows (5d8dac73/01bb89ee); payload-сравнение R-09.3 выполнено на уровне RecordingBot (полный diff, пересчёт приёмки `tools/rlr_r09_verify.py`).
- Чего не хватает (всё обязательно): релиз не выполнялся (`deployed_commit` пуст); прод-проверка не проводилась; живая Telegram-доставка не упражнялась; итог не записан в durable state как завершённый релиз.
- Карта: `R-DOD.9` PENDING, `R-PROC.5` PENDING.

## Сводка

| Пункт | Статус | Ключевой долг |
|---|---|---|
| 1 | proven | привязка `R-01.*`/`R-DEF.*` (clerical) |
| 2 | proven | — |
| 3 | partially | перепривязка `R-04.x`/`R-BAN.*`/`R-BND.4–10`; UI BGS-04 (волна UR-F/PVR) |
| 4 | proven | — |
| 5 | partially | привязка `R-05.2`/`R-06.9`; живая доставка — release/прод |
| 6 | partially | UI-часть `R-ADM.1/5/6/7` (волна UR-F/PVR) |
| 7 | proven | — |
| 8 | partially | route-matrix: переснять зоны RLR-03.3/RLR-08.14; приложение к отчёту |
| 9 | **not yet** | релиз + прод-проверка + живая доставка + durable-итог |

**Итог:** `proven` — 4 (пп. 1, 2, 4, 7); `partially` — 4 (пп. 3, 5, 6, 8); `not yet` — 1 (п. 9). DONE не провозглашается (R-09.5): релиз и прод-проверка не выполнены.
