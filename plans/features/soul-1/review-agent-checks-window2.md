# REV-AGENT-CHECKS-W2 — вердикт (окно-2 агентских проверок; прод 2.58.89)

Независимое ревью по сырым логам. Read-only; этот коммит — только данный документ.
**Биндинг:** прод `d59fab944bcb3eb0f5d3fa69101d8488da1c155b` (2.58.89); evidence-коммит `185cff1c` (15 файлов). `SHA256SUMS` пересчитан мной — **14/14**; `hash-bind-25889`: release-сторона **13/13** сверена мной с git-блобами `d59fab94` (все совпали), prod-сторона — из `P0_SHA` ранов; sha256 скрипта пробы == сессии #3 (`f9d94b6a…`).

## 1. CFG-01.AC1 — подтверждено (run1: G0–G10 все OK)
10→2 штатным `POST /api/config` без `X-Chat-Id` (updated=`limits.chat_burst_limit`); resolve `(2, 300.0, 'global')`; два `allow` израсходовали заряд (0.0/0.0, слот 2→1→0); **третий — полный `_handle_turn`** → фраза «дай передохнуть от твоей духоты, вернусь через 5 мин», `elapsed=0.0s`, без платных стадий; хвост `300s` == слот, `delta=0.0s`, «технически не могу» нет; вьюер `matched=2`, payload `{remaining_seconds:300.0, burst_limit:2, cooldown_seconds:300.0, source:'global'}`; возврат 10 → resolve `(10,300,'global')`, 3-й allow снова допущен; `NRestarts=0` до/после (MainPID тот же).

## 2. CFG-01.AC2 — подтверждено (H0–H7 все OK)
Чат-A: override `(2,180,'chat')`, поведение — 3-й ограничен (`179.99s`); чат-B при активном override A: `(10,300,'global')` — утечки нет, 3-й допущен; restore: `overrides_A={}`, resolve A снова global; профиль B не создавался (0 строк).

## 3. SOUL-AMD.8.3 (Style-половина) — подтверждено; **рекомендация: строку НЕ закрывать (остаток)**
- S1–S9 (run2, 28/28): try до правила не меняет текст; включённый пресет `trailing_period.hard.strip` (rev 6→7, rules=1) → **следующая try отдаёт текст без завершающей точки** (`repaired=1`, ревизия `c6.84cad658cf40`→`c7.e1a301d5414e`); мгновенный откат (rev=8, rules=0/soft=0), try снова не меняет; невалидное правило → явный issue `rule_kind_unknown:no_such_kind` + отброшено; fallback-композер (W3 принудительно недоступен) строит ref **только из реального документа** (hint == `_style_hint` реального docs, hidden-персонажа нет).
- **Остаток (не владельческий)**: (а) «во всех соответствующих путях» сейчас **нарушен реальным дефектом**: per-chat сохранение Style/Expression через MiniApp падает (`set_root`/`set_chat_params` без `pg` → `ChatLorePgUnavailable`; журнал 08:02:21 и 08:09:49; код `web/api/speech.py:2184`, `services/style_policy.py:2272` — подтверждено мной по коду релиза). Этот дефект **уже зарегистрирован** в P0-лейне (`plans/features/p0-save-init-ux/…`, слайс `P0A-PERSIST`: «Speech Style…», «Expression write_error»). (б) Core-половина и полный LLM-fallback требуют реальных генераций.
- Рекомендация леджеру: добавить production-эвиденс окна-2 к строке, **статус оставить READY_FOR_LIVE**, cross-ref на `p0-save-init-ux/P0A-PERSIST`; закрытие — после P0-фикса + живой проверки chat-scope save→next assembly и (опц.) Core/LLM-путей. Это не владельческий гейт — кодовая задача P0.

## 4. AMD.8.10 / 8.7 / 8.8 — подтверждено (run2: I/J/K все OK)
- 8.10: per-chat OFF → capability `disabled/module_disabled`; витрина `/speech/capabilities` и `/speech/overview` совпадают; L1 `_l1_capability_consistency` → `<capability_notice status="disabled">`, `denied=('image_generation',)`, без генерации; отказ == шаблон `message.image_failure.disabled`, 0 платных; возврат (`DELETE`) → 200, витрина `ready` после TTL (65 c). Остаток-примечание: смена провайдера живьём не форсировалась (мок-покрытие окна-1).
- 8.7: «сделай это» → `ambiguous/create_verb_without_object`; реальный гейт → ровно 1 сообщение, текст == шаблон «Уточни: картинку изобразить или текстом обойтись?», 0 платных.
- 8.8: OFF / нет ключа (`not_configured/key_absent`; per-chat override ключа, глобальный не тронут) / квота (`quota_exhausted/financial_limit_reached`, used=4≥limit=4) → **три разных правдивых текста == шаблонам**, `handled=True`, 0 вызовов провайдера, «я вообще не умею» нет. Остаток: «провайдер временно не отвечает» — мок (как в окне-1).

## 5. AMD.5.17 / 8.6 / 8.9 — подтверждено
- L1 (run2): реальный `_image_pre_gate_block` → `provider_calls=1`, `delivery="sent"`, реальная отправка `ok=true, message_id=195, bytes=1545484` (в ЛС владельца — синтетика недостижима, `getChat` BadRequest; это вынужденная адаптация брифа), **сообщение удалено** (`delete_message` mid=195); журнал резерва `990000811 committed, delivery_failed=False`.
- L2: повтор того же хода → `delivery="already"`, `provider_calls=0`, 0 отправок.
- 8.9 (run1 L3): реальный send-fail `TelegramBadRequest: chat not found` → блок `status="error" reason="delivery_failed"` + «Ничего не отправлено», «sent» не заявляется, авто-повтора нет; резерв `990000808 committed, delivery_failed=True`.
- **3 платных вызова за окно — приемлемо**: минимальные генерации, защита бюджета перед каждой, расход global 4→7 (лимит 200), chat 1→4 (лимит 60); все три привязаны к evidence (2 из них — send-fail/харнесс-кейсы, 1 — успешная доставка).

## 6. Гигиена — подтверждено
hash-bind 13/13 (двойная проверка); журнал: ERROR=0, CRITICAL=0, Traceback=2 — оба **до окна** (08:02:21/08:09:49, P0-дефект §3), разобраны в `recon-journal-tracebacks.txt`; синтетика снята (профили A/B 0, `throttle_state` 0, overrides {}, лимиты 10/300, `image_daily` 60 нетронут); `/tmp` очищен (`CLEANED=1`); `NRestarts=0`, 0 трекнутых правок прод-дерева (`recon-git-binding`: diff пуст; 13 записей — pre-existing untracked .bak).
Девиации (6, только харнесс): обрыв сессии #1 на PRE-STATE (несуществующая колонка; проба не запускалась); run1/L1 reply-таргет при редиректе (Telegram отклонил; исправлено, run2 успешен); run1/S3 отсутствие поля `changed` в `as_dict` (ассерт; факт был виден по тексту); полный `_handle_turn` в пробе упирается в `_build_user_content(memory=None)` до image-гейта (4 чек-а; закрыты вызовом реального гейта — паттерн окна-1); `grep -E` сниппет без `--`; `TRACKED_MOD=13` = untracked. Все 7 FAIL run-1 объяснены и перепроверены в run2 (ok=28/28).

## 7. Вердикт по строкам (леджеру)
| Строка | Решение | Остаток |
|---|---|---|
| CFG-01.AC1 | готово к VERIFIED | нет |
| CFG-01.AC2 | готово к VERIFIED | нет |
| SOUL-AMD.8.3 | **остаток: НЕ закрывать** (эвиденс записать) | «во всех путях» блокирован P0-дефектом chat-scope save (`P0A-PERSIST`); Core-половина/полный LLM-fallback — реальные генерации |
| SOUL-AMD.8.10 | готово к VERIFIED | смена провайдера — мок (примечание) |
| SOUL-AMD.8.7 | готово к VERIFIED | нет |
| SOUL-AMD.8.8 | готово для 3 условий | «провайдер временно не отвечает» — мок |
| SOUL-AMD.5.17 / 8.6 | готово к VERIFIED | нет |
| SOUL-AMD.8.9 | готово к VERIFIED | нет |
| SOUL-AMD.8.11 | остаток подтверждён | видео `not_configured (cobalt_absent)` — невоспроизводимо |
| INCIDENTAL (PERSIST) | вне лейна; cross-ref `p0-save-init-ux/P0A-PERSIST` | код-фикс P0-лейна, не владельческий гейт |

## Замечания
Блокирующих находок нет. Все использованные факты взяты мной из сырых ранов/логов, а не из README; release-сторона hash-bind и код PERSIST-дефекта проверены независимо.

## Вердикт
**Approved** (evidence-only; прод не менялся). Леджеру — применить таблицу §7: закрыть AC1/AC2, 8.10/8.7/8.8(3 условия)/5.17+8.6/8.9 с production-эвиденсом окна-2; AMD.8.3 — оставить RFL с cross-ref на P0.
