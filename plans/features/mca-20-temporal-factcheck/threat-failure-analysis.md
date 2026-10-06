# MCA-20 `mca-20-temporal-factcheck` — threat & failure analysis (Step 2 @Architect, 06.10.2026)

**Статус:** Risk **R3 CONFIRMED** (план `:211`; прецедент mca-18/19). Связка: `spec.md` (D1–D16), `adr-1028-20-temporal-factcheck.md` (D1–D14), санкции arch-frames §1.2.9.
**Scope анализа:** недоверенный контент с датами (текст/подписи/OCR/веб-страницы), snippet-инъекции в evidence, кеш-семантика (кросс-чат/отравление/stale), SSRF через проверяемые URL, ложный refuted / необоснованный misleading_reuse, ретроспектива как «знание автора», tool `fact_check`, приватность логов/событий, подмена времени.
**Методология:** STRIDE-lite по поверхностям; каждая угроза → вероятность/влияние → mitigation (design-level, где живёт) → residual. Ранги: Critical/High/Medium/Low. Критерий приёмки T-5149: Critical/High без mitigation = 0.

---

## 1. Поверхности и активы

| Поверхность | Активы |
|---|---|
| Вход: forward/reply/текст/подписи/OCR (v32 Origin, mca-19 analyses) | приватные тексты, даты оригиналов, OCR приватного |
| Веб-evidence (поиск/загрузка проверяемых URL) | snippet/страницы как недоверенные данные; SSRF-поверхность |
| TemporalClaimEnvelope/TemporalVerdict (v33 runs/evidence) | честность дат/статусов; привязка к сообщениям; attribution |
| Кеш (`factcheck_temporal` slug + legacy `factcheck`) | изоляция чатов/scope; свежесть; отсутствие кросс-контекстной выдачи |
| Tool `fact_check` | scope/права из runtime; отсутствие рекурсии; аргументы не из доверенного источника |
| «Аналитика» + routes runs | права просмотра; R17 (без приватного контента в общих видах/логах) |
| События mca-13 / логи | reason-коды/стадии — без контента (R17) |

---

## 2. Реестр угроз

### TH-1. Подмена времени недоверенным контентом (High→mitigated) — CA-20-7, `:1771–1779`
**Сценарий:** в тексте/OCR/на скриншоте дата «сегодня, 05.10.2026» или фальшивый «источник: опубликовано 01.01.2025» → бот принимает её за metadata, подменяет дату оригинала или выдаёт extracted за подтверждённую; EXIF подаётся как дата публикации.
**Mitigation (design):** priority-каскад `date_source` — Telegram metadata выше extracted всегда; extracted_claimed никогда не повышается молча (конфликт сохраняется и показывается, `temporal_date_conflict`); EXIF явно исключён из доказательства публикации (D5 spec); envelope собирается сервером из канонических метаданных — аргументы модели в даты не попадают (D2); канал извлечения — отдельно помеченный, недоверенный (spec D2/D16). Тесты A71/SC-R2c — блокер.
**Residual:** Low.

### TH-2. Snippet-инъекции / отравление evidence (High→mitigated) — `:1789`
**Сценарий:** поисковый snippet или страница содержат инструкцию/фабрикацию («verdict: refuted», скрытый текст, prompt-injection в цитате) → evidence переопределяет вердикт или уводит поиск.
**Mitigation:** evidence — недоверенные данные с обязательными полями provenance (URL/поддержка/retrieved_at/отношение к части); support — quoted/summarized с SourceRef-формой mca-04a; вердикт формирует analyst на структурированном payload (JSON-схема), а не на сырой конкатенации; validator (CoVe) перепроверяет связь «evidence ↔ часть claim»; фабрикация SourceRef запрещена; URL — только существующий fetch-контур/SafeFetcher (TH-3). Инъекция не может изменить режим/scope/даты envelope — они иммутабельны до стадий поиска (D1).
**Residual:** Low (семантическая уступка LLM — в пределах существующих текстовых гардов, как в mca-19 TH-1).

### TH-3. SSRF через проверяемые URL (High→mitigated) — `:1789`, SafeFetcher mca-02
**Сценарий:** claim/источник подсовывает URL внутренней сети/метаданных облака; redirect-цепочка; медленный drip.
**Mitigation:** никакого нового fetch-контура — существующие поисковый движок и SafeFetcher mca-02 (`MCA_SAFE_FETCH_ENABLED`/`MCA_EGRESS_GUARD_ENABLED` уважаются); tool `fact_check` не принимает URL от LLM (аргументы: claim/target/mode/period-hint, D4 spec); недоступная страница → `temporal_source_unavailable`, без «доказательства подделки» и без повторных попыток в цикле.
**Residual:** Low.

### TH-4. Кеш-отравление / кросс-чат / кросс-время (High→mitigated) — CA-20-8, `:1795`
**Сценарии:** (a) одинаковый текст 2022 и 2026 → старый вердикт выдан за новый; (b) атрибутированный ответ одного чата отдан другому; (c) unknown origin — ответ «привязан» к чужому сообщению; (d) stale hit получает сегодняшнюю дату проверки.
**Mitigation:** составной ключ (scope + claim/span + target revision/hash + origin fingerprint + режим+период + tzr-версия + MediaAnalysis revision + pipeline version + freshness bucket) — совпадение текста без совпадения контекста ключ не образует (D9 spec); unknown origin → ключ невозможен → авто-bypass (`temporal_cache_disabled`), атрибутированное не разделяется; as_of внутри payload — hit не «омолаживается»; legacy slug вне namespace без удаления (OFF-путь цел). Негативные тесты SC-R4a/R4b — блокер.
**Residual:** Low (формализовано тестами).

### TH-5. Ложный refuted / необоснованный misleading_reuse (High→mitigated) — CA-20-10/11, `:1789–1793`, no-false-acceptance
**Сценарии:** (a) поисковик недоступен → «утверждение ложно»; (b) первоисточник удалён → «подделка»; (c) обычная пересылка старого поста помечена «намеренно вводит в заблуждение».
**Mitigation:** отказ поиска → `insufficient_evidence` (никогда refuted); исчезнувшая страница → `temporal_source_unavailable` (F-2); `misleading_reuse` — только при признаках предъявления старого за новое (маркеры подачи), сам факт пересылки — не признак (D8 spec); возраст публикации сам по себе не делает утверждение ложным (contextual: old_but_valid). Тесты SC-R3b/R3c, A69 — блокер; Scanner T-5149 — dedicated-проверки.
**Residual:** Low.

### TH-6. Ретроспектива как «знание автора» (Medium→mitigated) — `:1783`
**Сценарий:** в режиме historical_truth бот использует расследование 2025 года и формулирует «автор знал/скрывал», смешивая с knowable_at_time.
**Mitigation:** режимы раздельны; историческая ретроспектива — только с явной меткой «установлено позднее»; knowable_at_time — свидетельства, доступные на дату; режим не подменяется fallback-ом молча (`temporal_fallback_mode` + assessment_mode в вердикте, D11 spec). Тест A71 — блокер.
**Residual:** Low.

### TH-7. Злоупотребление tool `fact_check` (Medium→mitigated) — CA-20-12, `:1765`
**Сценарии:** LLM подделывает target чужого чата/дату/источник; рекурсивный вызов fact_check раздувает цепочку; tool доступен при OFF.
**Mitigation:** scope/target — из доверенного runtime, от LLM не принимаются chat_id/URL/даты (D4 spec); free_text → explicit unknown origin без выдуманных message/date; рекурсия: внутренние стадии — data-only без инструментов + серверный depth-guard; OFF — скрытие tool + серверная проверка устаревших вызовов (defence in depth); вызов метричный (METERED_TOOLS), cache_hit — 0 токенов.
**Residual:** Low.

### TH-8. Приватность в логах/событиях/виджете (High→mitigated) — R17
**Сценарии:** claim-текст/evidence-цитаты приватных сообщений в структурных логах/событиях; runs другого чата видны в общих видах «Аналитики».
**Mitigation:** события `factcheck_temporal` — только id/коды/стадии/числа/refs (контента нет); run/evidence — durable записи под access_scope, просмотр — под действующими правами (routes с RBAC-прецедентом); логи — sanitize-контур R17 существующий; виджет не создаёт нового раздела и не расширяет аудиторию (SC-R5a). Scanner T-5149 — проверка каналов.
**Residual:** Low.

### TH-9. Timezone/точность — смещение границ суток (Medium→mitigated) — `:1781`
**Сценарий:** «событие 31.12 в 23:30 по местному» при неизвестном TZ трактуется как 01.01 UTC → неверный период/фрешность; точность day подменяется точным временем.
**Mitigation:** неизвестный TZ → интервал пограничных суток (не точка); precision хранится отдельно (day/month/year/interval/unknown); UTC-хранение ≠ TZ рендера; смена алгоритма → bump `tzr`-версии → старые ключи/записи не переиспользуются (D5/D10 spec). Тест «неизвестный timezone около полуночи» из матрицы `:1807` — блокер.
**Residual:** Low.

### TH-10. Stale/гонки: edited target, поздний media, параллельные проверки (Medium→mitigated) — `:1807`
**Сценарии:** target отредактирован после вердикта → устаревший ответ; MediaAnalysis стал ready после начала фактчека → молчаливая подмена дат; два одновременных запроса — двойной расход.
**Mitigation:** target revision/content_hash в ключе и записи (edit → новый контекст); поздний media — честный `temporal_media_pending`, вердикт не переписывается молча (новый прогон — только явный запрос); существующий пул per-chat (`smartmodule_concurrency`) + кулдаун хендлера — REUSE (дубли не образуют лавины; LLM-вызов метричный); CAS-семантика записи run по revision (v33).
**Residual:** Low.

### TH-11. Ложные статусы UI / observability-обман (Medium→mitigated) — `:1791`, `:1805`
**Сценарий:** «проверено» при упавшем поиске; кеш-hit показан как свежая проверка; fallback скрыт.
**Mitigation:** factual_verdict/temporal_status — CHECK-enum в схеме; reason-словарь +10 (insufficient/source_unavailable/fallback/cache_disabled/…); «почему выбрана эта дата» = date_source+uncertainty+каскад в виджете; cache_hit/version/fallback_visible — обязательные поля UI (D14/D11 spec). Тест A73 — блокер.
**Residual:** Low.

### TH-12. Retention/рост v33 (Low→accepted)
**Сценарий:** runs/evidence накапливаются; удалённые сообщения «воскрешаются» через детали run.
**Mitigation:** просмотр — под правами и scope; политика хранения — существующий контур (mca-13 retention); run не восстанавливает удалённый контент в чат — это аналитическая запись; счётчики витрины агрегированы.
**Residual:** Low, disclosed.

---

## 3. Failure modes (корректность, не безопасность)

| # | Отказ | Поведение по дизайну |
|---|---|---|
| F-1 | Поисковые движки недоступны | `insufficient_evidence` + `temporal_insufficient_evidence`; не refuted; retry — ограниченный, существующий |
| F-2 | Первоисточник исчез/недоступен | `temporal_source_unavailable`; не доказательство подделки |
| F-3 | Дата не извлеклась (парсинг упал) | `temporal_date_extract_failed` ≠ `temporal_date_unknown`; now не подставляется |
| F-4 | Конфликт дат (extracted vs Telegram) | конфликт сохранён и показан, не разрешён молча |
| F-5 | Fallback сменил ветку/режим | явный статус (`temporal_fallback_mode`), historical↔current не меняются молча |
| F-6 | Ключ кеша не построен (unknown origin) | авто-bypass: вычисление без кеширования вердиктов; поиск/загрузки кешируются |
| F-7 | Media pending / late ready | честный `temporal_media_pending`; вердикт не переписывается молча; новый прогон — по явному запросу |

---

## 4. Вывод

Risk **R3 подтверждён**. Critical-угроз в дизайне **нет**; все High закрыты design-level митигациями с блокер-тестами (A69–A72, SC-R2c/R3b/R3c/R4a/R4b) и вынесены в Scanner-чеклист T-5149. Residual: (1) семантическая уступка LLM недоверенному контенту (инъекции/даты) — в пределах существующих текстовых гардов + каскад дат + JSON-схема вердикта, disclosed; (2) внешний поиск не exactly-once — расход метричный, кулдаун/пул существуют. Санкции (v33, +4/+1 каталог с F8, 3 kill-switch, +10 reason_code, тулы 13→14, CA-11 2.58.64) безопасности не ослабляют: OFF = бит-в-бит `d298f1f`/2.58.63, URL — только SafeFetcher, R17-запреты в SC-R5a.

R17: секретов в документе нет.
