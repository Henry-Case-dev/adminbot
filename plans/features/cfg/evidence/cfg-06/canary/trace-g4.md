# CFG-06 F.1 stage trace — канарейка G.4 новость/дата (v2 @ 7142ffcf, флаг ON)

Контур: тестовый (мок Telegram; реальный поиск Tavily/Exa/DDG, реальная LLM `deepseek-v4-flash`). Синтетический chat_id, ноль сообщений в реальные чаты. `db=None` → ветка `legacy_single` единого оркестратора (envelope-контур требует приватную БД чата — в тестовом контуре честно отсутствует; контур прод-пути 06H.2 покрывают CONTRACT-тесты W3/W6).

| Стадия | Факт прогона |
|---|---|
| target_resolve | db=None (контур) → envelope пропущен, маршрут `legacy_single` (единый вход run_factcheck, 06H.2) |
| suitability | checkable_in_context / тип `checkable_factual_claim`; claim_items=1; scope=web; reason=obvious_checkable_predicate; confidence=0.8; temporal_hint=True |
| plan | запросов=3; `население земли превысило миллиардов человек ноября 2022 года` [entity_check]; `население земли превысило миллиардов человек ноября 2022 года 8 м 15 2022 г` [numeric_verification]; `население земли превысило миллиардов человек ноября 2022 года 2022` [temporal_context] |
| retrieval (web) | attempted=3, used=3, search_text=7504 симв; бюджет исчерпан=False; версия планера=fp1 |
| retrieval tool call | query=`население земли превысило миллиардов человек ноября 2022 года` → ok=True, 2.64 с, 2500 симв, URL в выдаче: https://ru.wikipedia.org/wiki/%D0%9D%D0%B0%D1%81%D0%B5%D0%BB%D0%B5%D0%BD%D0%B8%D0%B5_%D0%97%D0%B5%D0%BC%D0%BB%D0%B8, https://www.tadviser.ru/index.php/%D0%A1%D1%82%D0 |
| retrieval tool call | query=`население земли превысило миллиардов человек ноября 2022 года 8 м 15 2022 г` → ok=True, 1.58 с, 2500 симв, URL в выдаче: https://www.stena.ee/blog/etoj-osenyu-naselenie-zemli-prevysit-8-milliardov-chelovek-kogda-i-pochemu-mir-nachal-rasti, https://kyrgyzstan. |
| retrieval tool call | query=`население земли превысило миллиардов человек ноября 2022 года 2022` → ok=True, 1.55 с, 2500 симв, URL в выдаче: https://theworldonly.org/rost-naseleniya-zemli-6-milliardov-za-poslednie-200-let, https://ru.wikipedia.org/wiki/%D0%9D%D0%B0%D1%81%D0%B5%D0%BB%D0%B5%D0%BD%D0%B8%D0%B5_%D0%97%D0%B5%D0%BC%D0%BB%D0%B |
| evidence_validate | refs=12 (ev-N текущего прогона); primary fetch: https://ru.wikipedia.org/wiki/%D0%9D%D0%B0%D1%81%D0%B5%D0%BB%D0%B5%D0% → ok (published_at=None); https://www.tadviser.ru/index.php/%D0%A1%D1%82%D0 → ok (published_at=None) |
| analyst/verbalizer LLM | step=stage1, ok=True, 9.27 с, in=9651/out=1767 симв, model=deepseek-v4-flash |
| analyst/verbalizer LLM | step=stage2, ok=True, 7.2 с, in=3068/out=1315 симв, model=deepseek-v4-flash |
| presentation (egress) | служебных маркеров нет=True; admin-токенов нет=True; сырой слайс-эхо нет=True |
| render | parse_mode=HTML по всем чанкам=True; чанков=1 (len 1562) |
| Telegram delivery (МОК) | отправок=1; reply только у первой=True; реальных вызовов Telegram API=0 |

## Стоимость и причины деградации

- Платные вызовы: LLM=2 (steps: stage1,stage2), веб-поиск=3, primary-fetch=2.
- Деградации (честные, из логов прогона): см. `logs` в run-g4.json.
- Admin-наблюдаемость: mca-события `factcheck_run` (retrieval+итог), `safe_fetch` start/failed, logger-дайджест `[factcheck_v2] retrieval | attempted|used|refs|fetch_errors|budget` — в `logs`; приватных текстов и секретов в событиях нет (синтетический chat_id).
- User vs admin: в user-payload нет reason-кодов/метрик/запросов; детали — только здесь (admin-файл).
