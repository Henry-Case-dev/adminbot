# CFG-06 F.1 stage trace — канарейка G.1 Saccharomyces (v2 @ 7142ffcf, флаг ON)

Контур: тестовый (мок Telegram; реальный поиск Tavily/Exa/DDG, реальная LLM `deepseek-v4-flash`). Синтетический chat_id, ноль сообщений в реальные чаты. `db=None` → ветка `legacy_single` единого оркестратора (envelope-контур требует приватную БД чата — в тестовом контуре честно отсутствует; контур прод-пути 06H.2 покрывают CONTRACT-тесты W3/W6).

| Стадия | Факт прогона |
|---|---|
| target_resolve | db=None (контур) → envelope пропущен, маршрут `legacy_single` (единый вход run_factcheck, 06H.2) |
| suitability | checkable_in_context / тип `checkable_factual_claim`; claim_items=1; scope=web; reason=obvious_checkable_predicate; confidence=0.8; temporal_hint=False |
| plan | запросов=1; `дрожжи грибы бактерии поэтому пробиотики saccharomyces boulardii восстанавливают` [entity_check] |
| retrieval (web) | attempted=1, used=1, search_text=2500 симв; бюджет исчерпан=False; версия планера=fp1 |
| retrieval tool call | query=`дрожжи грибы бактерии поэтому пробиотики saccharomyces boulardii восстанавливают` → ok=True, 3.91 с, 2500 симв, URL в выдаче: https://www.eurolek.com.ua/ru/blog/chto-takoe-saharomiczety-bulardi-saccharomyces-boulardii, https://farmplus.com.ua/ru/miscze-saccharomyces-boulardii-sered-suchasnyh-probiotychnyh-produktiv |
| evidence_validate | refs=4 (ev-N текущего прогона); primary fetch: https://www.eurolek.com.ua/ru/blog/chto-takoe-saharomiczety-bulardi-sa → FAIL (причина в safe_fetch-логе); https://farmplus.com.ua/ru/miscze-saccharomyces-boulardii-sered-suchas → FAIL (причина в safe_fetch-логе) |
| analyst/verbalizer LLM | step=stage1, ok=True, 11.0 с, in=4706/out=1739 симв, model=deepseek-v4-flash |
| analyst/verbalizer LLM | step=stage2, ok=True, 6.31 с, in=3688/out=1524 симв, model=deepseek-v4-flash |
| analyst/verbalizer LLM | step=stage2, ok=True, 8.89 с, in=3803/out=1865 симв, model=deepseek-v4-flash |
| presentation (egress) | служебных маркеров нет=True; admin-токенов нет=True; сырой слайс-эхо нет=True |
| render | parse_mode=HTML по всем чанкам=True; чанков=1 (len 2135) |
| Telegram delivery (МОК) | отправок=1; reply только у первой=True; реальных вызовов Telegram API=0 |

## Стоимость и причины деградации

- Платные вызовы: LLM=3 (steps: stage1,stage2,stage2), веб-поиск=1, primary-fetch=2.
- Деградации (честные, из логов прогона): см. `logs` в run-g1.json.
- Admin-наблюдаемость: mca-события `factcheck_run` (retrieval+итог), `safe_fetch` start/failed, logger-дайджест `[factcheck_v2] retrieval | attempted|used|refs|fetch_errors|budget` — в `logs`; приватных текстов и секретов в событиях нет (синтетический chat_id).
- User vs admin: в user-payload нет reason-кодов/метрик/запросов; детали — только здесь (admin-файл).
