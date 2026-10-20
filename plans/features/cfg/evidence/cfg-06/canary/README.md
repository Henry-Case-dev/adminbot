# CFG-06 postdeploy canary — 06E.4 / 06F.1 / 06G.1 / 06G.4

Дата: 20.10.2026. Код: deployed **2.58.99 @ `7142ffcf`**, флаг
`FACTCHECK_PIPELINE_V2_ENABLED=true` (env тест-контура; в проде флаг включён
hot-параметром `flags.factcheck_pipeline_v2` — тот же гейт
`pipeline_v2_enabled()`, приоритет hot → env, `factcheck_orchestrator.py`).

**Байт-равенство:** прогоны выполнены на локальном дереве `29b91004` =
`7142ffcf` + samples-ux; `git diff --stat 7142ffcf HEAD` по всем 8
фактчек-файлам (handlers/factcheck.py, services/factcheck_*.py,
config/settings.py) **пуст** → код байт-равен проде.

**Контур:** единый вход `run_factcheck` целиком; поиск — реальный каскад
SearchAggregator (Tavily ключ тест-контура; Exa/DDG — фолбеки), LLM —
реальная (`deepseek-v4-flash`, apinet.cloud), Telegram — **МОК** (FakeBot
только записывает отправки; ноль обращений к Telegram API, ноль сообщений в
реальные чаты). `db=None` → ветка `legacy_single` с единым retrieval-контуром
W6; envelope-ветка требует приватную БД чата — в тестовом контуре честно
отсутствует (её контракты фризятся CONTRACT-тестами W3/W6/W7).

**Стоимость:** 2 платных прогона v2 (лимит ≤6): LLM-вызовов 5 (3+2),
веб-поиска 4 (1+3, все Tavily ok), primary-fetch 4 (2 ok / 2 fail — честно
записано). Renderer/delivery E.4 — без платных вызовов.

## Вердикты по строкам

### 06G.1 — PASS
Клейм биологического спора («дрожжи — это грибы, а не бактерии, поэтому
пробиотики с Saccharomyces boulardii восстанавливают микрофлору после
антибиотиков»).
- атомарный тезис выделен гейтом (`checkable_in_context`, claim_items=1,
  reason=obvious_checkable_predicate);
- запрос осмысленный, НЕ дословный слайс: `дрожжи грибы бактерии поэтому
  пробиотики saccharomyces boulardii восстанавливают` [entity_check] —
  **биномен сохранён полностью**;
- реальный поиск: Tavily ok (3.9 c, 2500 симв), источники с URL;
- EvidenceMap: 4 refs (ev-1..ev-4, URL отдельно от текста; 2 primary-fetch
  попытки failed `too_many_bytes` — честная деградация, budget не исчерпан);
- вердикт отделяет корректную часть от ошибочной: «дрожжи — грибы» и
  пробиотический эффект S. boulardii подтверждены, ложная причинность
  «гриб, а не бактерия, ПОЭТОМУ восстанавливает микрофлору» выделена и
  исправлена («без "поэтому" между таксономией и терапевтическим эффектом»);
- renderer payload: 1 чанк HTML 2135 симв ≤4096, 2 inline-href строго из
  EvidenceMap, служебных полей нет, reply-якорь на цели.
Файлы: `run-g1.json` (прогоны+проверки+логи), `trace-g1.md` (F.1-трасса),
`preflight.json` (детерминированная часть).

### 06G.4 — PASS
Клейм дата/статистика: «Население Земли превысило 8 миллиардов человек
15 ноября 2022 года».
- реальный веб-вызов: 3 запроса Tavily, все ok, **3 разных интента**
  (entity_check / numeric_verification / temporal_context, год-хвост 2022);
- релевантная выдача: Wikipedia «Население Земли», материалы о «Дне восьми
  миллиардов» ООН;
- проверка публикации: 2 primary-fetch через SafeFetcher **успешны**
  (ru.wikipedia.org, tadviser.ru, 141/600 симв), `parse_publication_date`
  честно не нашёл дату в разметке страниц → published_at=None, выдуманных
  дат в вердикте нет (ограничение честное);
- inline-ссылки на фактически использованные источники: 2 href из
  EvidenceMap текущего прогона;
- вердикт: подтверждение с честной оговоркой (веха ООН — прогнозная дата,
  а не перепись), без самоуверенности.
**Инцидент (related-nonblocking, в леджер отдельно):** URL
`https://www.tadviser.ru/index.php/%D0%A1%D1%82%D0…` усечён — лимит
`max_symbols=2500` агрегатора срезал строку выдачи вместе с URL; рендер взял
его как есть (`\S+`-whitelist пропускает). Ссылка кликабельна, но ведёт на
404; ссылка Wikipedia полная и рабочая. Корень — обрезка по символам на
уровне агрегатора (существующий контракт Epic 33), не в CFG-06 коде.
Файлы: `run-g4.json`, `trace-g4.md`.

### 06E.4 — PASS
renderer+delivery через СУЩЕСТВУЮЩИЙ `send_chunked_reply(parse_mode="HTML")`
на моке Telegram, 3+1 варианта:
1. **длинный (6358 симв) с URL+Unicode** → 2 чанка (3247/3110 ≤4096); теги
   не рваны (баланс b/i/a в каждом чанке); Unicode-сентинелы (—, 🧬, 联合,
   «кавычки», combining U+0301/U+0306) сохранены; каждая ссылка ровно 1 раз
   (href `&` корректно экранирован как `&amp;` — контракт Telegram-HTML);
   библиография не дублируется (1 блок); reply только у первой части.
2. **пустой evidence** → честное ограничение «Первоисточники в этот раз
   открыть не удалось…», ссылок нет, «проверено в интернете» не заявлено.
3. **перегруженный HTML** (script/инъекции/незакрытые теги) → всё
   экранировано: живых `<script>` нет, реальных href вне whitelist нет,
   `javascript:` только как видимый текст.
4. **неожиданный ввод** (TelegramBadRequest на чанке с маркером) → 2 HTML
   чанка прошли, РОВНО сломанный чанк деградировал в plain visible-text,
   reply-якорь не задублён.
Файл: `run-e4.json` (все проверки + тексты чанков).

### 06F.1 — PASS
На каждом прогоне G.1/G.4 собрана полная stage trace
`target_resolve → suitability → plan → retrieval → evidence_validate →
analyst/verdict → presentation → render → delivery` (см. `trace-g1.md` /
`trace-g4.md`): фактические tool calls (Tavily-запросы с латентностями,
primary-fetch с исходами, LLM stage1/stage2 с in/out и латентностями),
статусы, стоимость, причины деградаций (G.1: 2×`too_many_bytes` primary
fetch + bounded retry вербализатора attempts=2; G.4: published_at не
извлечён — честно). Админ-наблюдаемость реальными механизмами: mca-события
`factcheck_run` (retrieval + итог, outcome=success), `safe_fetch`
start/failed с reason_code, logger-дайджест `[factcheck_v2] retrieval |
attempted= used= refs= fetch_errors= budget_exhausted=` — всё в `logs`
внутри run-файлов. Пользователю — только результат (все проверки
`no_service_markers`/`no_admin_tokens` = True), детали — в admin-файлах;
секретов и приватных текстов в трассах нет (chat_id синтетический).

## Ограничения (честно)
- Envelope-ветка ( temporal-контур MCA-20) в канарейке не прогонялась —
  требует приватную БД чата; её контракты фризятся тестами W3/W6/W7 и не
  входят в объём этих 4 строк.
- G.4: публикационная дата не извлечена на выбранных страницах — механизм
  попытки доказан, даты не выдуманы (соответствует 06E.7).
- Усечённый URL из Tavily-сниппета — существующий контракт агрегатора
  (Epic 33), зафиксирован как related-nonblocking.
