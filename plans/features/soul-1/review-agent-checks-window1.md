# REV-AGENT-CHECKS-1 — вердикт (окно agent-checks-1; прод 2.58.88)

Независимое ревью по сырым логам (evidence-only). Прод не менялся; этот коммит — только данный документ.

## 0. Привязка кандидата и провенанс
- Кандидат: прод HEAD `c37b85779cc41ad716304024ebeea86ad4081071` = 2.58.88; оба прогона: `HEAD=c37b8577…`, `TRACKED_MOD=0`, healthz `{"status":"ok","version":"2.58.88"}`.
- Evidence: `plans/features/soul-1/evidence/agent-checks-window1/**` (15 артефактов). `SHA256SUMS.txt` пересчитан мной: **15/15** (хеш+размер) — ок.
- `hash-bind-25888.txt`: release-сторона **12/12** сверена мной с реальными git-объектами `c37b8577` (все совпали); prod-сторона = строки `AC1 P0_SHA` из сырых ранов (совпадают). Проба исполнялась в `/var/www/admin_bot` (venv; `os.chdir`+`sys.path.insert`; `sha12()` читает файлы прод-дерева) — доказательства привязаны к развёрнутому кандидату.
- Скрипты — реальные драйверы прод-кода: `DirectChatService._handle_turn`, `persistent_throttling.throttle_refresh`, `response_extent.check_extent`, `_image_pre_gate_block`, `image_generation.maybe_handle_keyword`, `capability_registry.resolve/status_message`, `style_policy.build_document/effective_policy_sync/apply_style_policy`; реальные API (`/api/config` c `X-Chat-Id`, `/api/speech/try`, `/api/speech/style`, `/api/status/logs`) c реальным `init_data` (HMAC на `settings.API_TOKEN`, значение не печатается; journal `[tma-auth] valid=True`=21); спай `ig._generate_post/_generate_get` — счётчик фактических провайдерских вызовов. Фабрикации выводов не обнаружено.
- Прогон 1 недействителен для OQ-12/D7 (дефекты харнесса, см. §7); каждый использованный ниже факт взят из прогона, где соответствующая проверка прошла (run-1: B/C/D4–D6/E/F; run-2: A/D7/D8, `ok=15/15`).

## 1. OQ-12 (CFG-01, живая половина) — подтверждено (run-2)
- A2: `POST /api/config` (X-Chat-Id=синтетика) → 200, `updated=['limits.chat_burst_limit','limits.chat_cooldown_seconds']`, burst=1/cooldown=180.
- A3: эффективный резолв `burst=1 cooldown=180.0 source='chat'`.
- A4–A7: реальный `_handle_turn` → фраза `рот оффни на 3 мин, я не нанимался с тобой болтать без остановки`; хвост `3 мин` == расчёт по `last_ts` слота (`db_remaining=180.0s`, `delta=0.0s`, `formatted==db-based`); «технически не могу» нет. Прод-лог: `[direct] cooldown | chat=-1009900000201 … remaining=180s | burst_limit=1 cooldown=180.0 source=chat` + mca-событие `direct_chat_throttle stage=cooldown outcome=skipped reason_code=rate_limit`.
- A10/A11: вьюер `GET /api/status/logs?component=direct_chat` → `events=1 matched=1`; payload `usage_json={"remaining_seconds":180.0,"burst_limit":1,"cooldown_seconds":180.0,"source":"chat"}`.
- A12/A13 + state-pre-post: профиль 0, `throttle_state` 0, `overrides={}`, глобальные 10/300 не тронуты; durable mca-событие оставлено как evidence.
- Отказ до платных стадий: сервис собран с `llm=None`, отправка за 0.0s, провайдерских вызовов нет.

## 2. OQ-9(a) — подтверждено; семантика принята
- 9 кейсов реального `check_extent` (run-1, `B1_form_matrix OK`): `Да!!!`/`OK!!!`/`по-хорошему`/`да` → pass без изменений; `Да, конечно, всё сделаю` → failed `one_word_multiple_words`, текст НЕ обрезан; `Готово 🔥` → repaired `one_word_extra_tail_removed`; micro: 1 слово и 4 слова pass, 12 слов pass c `micro_soft_exceeded`.
- **Согласен: это корректная семантика.** SOUL-05.5: одно слово с учётом восклицаний/составных/латиницы; при нарушении — минимальная локальная коррекция; обрезка содержательного текста отсутствует. SOUL-05.3: micro без жёсткого лимита (soft-exceeded), остаётся отдельным extent.
- B2: реальный `POST /api/speech/try` на 4 входах — 200, `layers_current=[channel_contract,channel_contract,core]`, 7 extent-значений, `delivery=false`, 0 LLM.

## 3. OQ-9(b) — подтверждено с документированным нюансом
- C3: запись scope=global → `applied=true revision=3` (одна выключенная soft-инструкция, enabled=false — нулевое влияние).
- C4: следующая try видит новую ревизию: `versions.style_policy c2.75bada4c52c3 → c3.5bc205ee3e86` (ассерт run-1 ждал префикс `g3` — дефект харнесса; сам факт подтверждён).
- C5/C6: восстановление → `revision=4`, `rules=0/soft=0`, проба-инструкция удалена (`probe_soft_present=False`); state-pre-post: history 3/2/1, текущая 4; P0: `style.policy` в PG был (value_len=545).
- Нюанс ревизии (номера 2→4, history 3/4) — штатная модель истории; отдельного API удаления глобального документа нет; содержимое по смыслу восстановлено — принято.

## 4. OQ-9(c) — подтверждено
- D1: 10 фраз реального `detect_action_intent`: поручения `create_image/high/actionable=true`; «но не рисуй» → `create_image_negated/actionable=false` (при `is_keyword_regex=true`); «придумай концепт…» → `create_image_conceive_only=false`; «обсудим»/«сам нарисую»/цитата/«мемориальный комплекс» — не поручение; «сделай это» → ambiguous.
- D2: реальный `_image_pre_gate_block` — блок пуст, `generated_calls=0` при обоих отрицаниях, хотя regex-дверь открыта. **Приемлемо**: production-путь гейтится семантическим интентом до генерации (5.10 VERIFIED); regex не является единственной точкой доступа.
- D4: реальная генерация через `maybe_handle_keyword` (`intent_confirmed=true`): `provider_calls=1`, блок `delivery="sent"`, `send_photo`=1 (стаб) 1604304 байт, journal `image_reservation -1009900000201:990000701:direct → committed`. Квота: run-1 P0 global=2 → run-2 P0 global=3, `chat:-1009900000201 image_calls=1`.
- D5: повтор того же хода → `delivery="already"`, `provider_calls=0`. D9: всего вызовов провайдера за фазу 1.

## 5. OQ-9(d) — подтверждено (run-2)
- D7: per-chat OFF (`flags.image_generation_module_enabled=false`) → capability `disabled/module_disabled`; реальный `_image_capability_gate`: `handled=true provider_calls=0`, текст РОВНО из шаблона `message.image_failure.disabled` («Рисовать я сейчас не могу…»), «я не умею» отсутствует. D8: `overrides_after={}`.

## 6. OQ-9(e)/(f) — подтверждено; видео — принятый остаток
- E1: реальный `execute_web_search` 2.5s, 4039 символов, реальные результаты. E2: реальный `fact_check` 23.6s, `status=ready`, `factual_verdict=supported`, `temporal_status=old_but_valid`, durable `tfr-38ab2b7fa98b44cb` (в журнале — честные safe_fetch-предупреждения, вердикт не маскирован).
- E3: `video_summary = not_configured (media_source_unconfigured/cobalt_absent)`. **Принимаю остаток**: бриф «видео — если воспроизводимо»; без включения медиа-источника сценарий невыполним; capability честно сообщает недоступность.
- F1: реальный try 568 знаков, `editorial_report`, `protected_count=4` (kinds code/version_literal). F2: реальные функции style_policy с 3 жёсткими пресетами (record=false): URL, цитата, код, версия сохранены; честный `conflicts=["quotation_marks.hard.no_graphic"]`; изменение только завершающая точка (568→566).

## 7. Гигиена — подтверждено
- Журнал окна: ERROR=0, CRITICAL=0, Traceback=0, `[tma-auth] valid=True`=21, healthz 2.58.88 (сырой блок run-2).
- 4 девиации + примечание — только харнесс, не продукт: (1) run-1 прайм до `throttle_refresh` → ход ушёл в LLM-ветку внутри процесса пробы, `AttributeError: 'NoneType' … get_window_messages`, ответ ERROR-фразой; прод-процесс не затронут (отдельный процесс; журнал 0 ERROR), исправлено — run-2 чист; (2) run-1 C4 — ассерт префикса `g` vs `c`; (3) run-1 фаза D — override до создания профиля → 409; исправлено `ensure_scope_profile`; (4) run-1 раннер — expect совпал с эхо-строкой → один неудачный `sudo` («Sorry, try again», одна SSH-сессия, без повторов/перебора) — исправлено lookbehind; (5-примечание) повторная генерация изображения в run-2 не запускалась (`AC1_SKIP_IMAGE_GEN=1`).
- Синтетические следы (все привязаны к `-1009900000201`): 1 mca-событие (evidence вьюера), 1 `image_reservation…committed`, 1 `mca_factcheck_runs`, `style.policy` rev=4 (rules=0/soft=0). Снято: профиль 0, throttle_state 0, overrides={}. Глобальные лимиты 10/300 до/после.
- Секреты: значений нет; в evidence только эхо-приглашение `[sudo] password for nik:` и заведомо фейковый `TEST_TOKEN` локального smoke; раннеры scrubb-ят пароль.

## 8. Готовность к леджеру (построчно)
| Строка | Решение | Остаток сверх доказательств |
|---|---|---|
| CFG-01.6 | готово к VERIFIED | нет |
| CFG-01.AC4 | готово к VERIFIED | нет |
| CFG-01.AC1 | остаток | буквальный сценарий «глобальный burst 10→2 → 3-й запрос ограничен → возврат без рестарта» не исполнялся; эквивалентный hot-путь подтверждён на chat-scope. Закрытие: короткий агентский прогон с мгновенным возвратом ЛИБО явное принятие эквивалентности (решение леджера/PM) |
| CFG-01.AC2 | остаток (минимальный) | живой резолв «второго чата по global» не наблюдался; утечки override нет (global 10/300 до/после; source='chat' только у синтетики). Закрытие: один resolves-чек ЛИБО принятие |
| SOUL-05.2/05.3/05.5 | готово к VERIFIED (агентская часть по брифу §3) | реальный ответ в чате — необязательная владельческая наблюдаемость (§4); леджеру поправить reason-рамку (см. §9.1) |
| SOUL-AMD.8.3 | готово к VERIFIED по пункту «видит новую ревизию» | эффект включённого правила на текст генерации и «во всех путях» не проверялись (проба сознательно enabled=false); fallback-клауза — вне окна |
| SOUL-AMD.5.17, AMD.8.6 | готово частично | реальный Telegram-send (в окне — стаб; провайдер — реальный) и случай фактической ошибки доставки |
| SOUL-AMD.8.7 | готово частично | живое уточняющее сообщение для «сделай это» (в окне — только классификация) |
| SOUL-AMD.8.8 | готово частично (OFF-кейс живой) | 3 условия (нет ключа/провайдер/квота) — мок-покрытие, live не форсировались |
| SOUL-AMD.8.9 | готово частично | send-fail кейс («отправил» не заявляется) не форсировался |
| SOUL-AMD.8.10 | готово частично | UI-витрина capability, смена провайдера/глобальный модуль — не наблюдались |
| SOUL-AMD.8.11 | готово для поиска/фактчека | видео — not_configured (cobalt_absent), не воспроизводимо; принятый остаток |
| SOUL-AMD.1.7 | готово к VERIFIED | реальная длинная публикация — необязательная наблюдаемость |

Не покрыто этим окном (не закрывать по этому evidence): SOUL-05.6, SOUL-10.P5, SOUL-11.4, SOUL-12.2, SOUL-12.5, SOUL-18.6. SOUL-AMD.5.9/5.10 уже VERIFIED — окно лишь повторно подтвердило живую семантику.

## 9. Замечания (не блокирующие; для леджера)
1. Reason-формулировки строк (SOUL-05.2/05.3/05.5, AMD.8.3/8.6–8.11) всё ещё содержат старую рамку «owner-сценарий / чек-лист postdeploy-observations; строки НЕ закрываются до живого подтверждения». По действующей переклассификации (директива владельца 18.10; `owner_questions.md` §§3–6) это уже неверно: агентская часть — данные проверки, живой чат/доставка/публикация — необязательная наблюдаемость (§4). Леджеру обновить формулировки при проставлении VERIFIED; новых владельческих гейтов не создавать.
2. CFG-01.AC1/AC2 — минимальные остатки (см. таблицу §8).
3. Нюанс style.policy (rev 2→4) — штатная ревизионная модель, содержимое восстановлено; принято.
4. Run-1 `A5_refusal_sent` без поля `error_phrase` дал ложный OK на ERROR-фразе; в run-2 чекер исправлен (`error_phrase=false`). Продукт не затронут.
5. `A8_no_llm_call` — слабое (тавтологичное при `llm=None`) утверждение; фактическая сторона «отказ до платных стадий» подтверждена A5 (0.0s), прод-логом cooldown и отсутствием провайдерских вызовов.

## Вердикт
**Approved** (evidence-only). Продуктовых дефектов в окне не найдено; пункты задания 1–7 подтверждены по сырым логам и привязаны к `c37b8577`; пункт 8 — построчные решения выше. Каталог evidence на момент ревью untracked — его коммит за лейном вместе с леджерным обновлением; данный коммит содержит только вердикт.
