# REV-TAILS-2 — ревью трёх ledger+harness коммитов (22.10.2026)

Вердикт: **Approved ×3** (81419cfd asap8, c39c776e cfg CFG-02A, 20bc0dc3 p0b) поверх db2b7044.

## Реверифицировано (выборочно, по сырому артефакту)
- asap8: U07.1a (owner-директива 18.10, platform-верификация, release-fs-25884), REQ-0-1 (биндинг baseline/probe-exec/tick-observation), V02/V03 (harness-experience.json: 6 реальных provider-вызовов, window2 5/5 чеков), B10-R15 (dream-gate-on-harness.json: gate ON distilled=2/deferred=1/watermark; deep written=1, run_at честные).
- cfg CFG-02A (.3/.4/.5+AC1): cfg02a-harness.json 15/15 — A1–A6 (UI write-path → worker_budget → генерация без рестарта), B1–B3 (отказ до платного вызова, provider_calls=0, reset 00:00 chat-TZ Asia/Yekaterinburg), C1–C6 (override сильнее GLOBAL, переживает перечитку, DELETE → наследование); AC1: rc=0, console_errors=0, machine-facts 360×780/1280×800 (facts_present=true, overflow_x=false) + скриншоты.
- p0b: nost-scen-b-harness.json 3/3 (днём отправка 1; повтор 0; тихие часы 0); live-scenarios-load.json V1 100k строк / тик 2.855с / 1 LLM-вызов (без последовательного прохода), V2 gap 10k → digest, V3 новый чат 8 сообщений.

## Harness-реальность
- Реальные вызовы: OpenRouter deepseek-chat-v3-0324 (6) в window1; замена apinet задокументирована в README с probe_llm 21–22.10 (ConnectTimeout с dev-машины). Замена допустима: acceptance-контракт — провайдер-агностичный semantic-слой (JSON-схемы, lesson lifecycle), не конкретный провайдер.
- FakeBot/Telegram не использовался — корректно для проверявшихся механизмов; счётчики/тайминги/tz во всех артефактах есть; glass-video — реальный Chrome + webm/кадры + sha в meta.json.

## Честность остатков
- 5 RFL asap8 подтверждены как реальные WAITING_EXTERNAL/факт-остатки: B09/B10-R10 (chat_id_migrations пуста на проде — нет внешнего события migrate), B10-R06 (квота эмбеддингов провайдера, journal EMBED_API_DEFERRED ×357/7д), B10-R11 (живые примеры запретов в естественном потоке), REQ-B11-E2E (честно: «строка не закрыта»). Замылки не найдено; context-реклассификация 8 строк (L32/L46/L418/L437/L445 — заголовки, L447–449 — пределы) сверена с исходником — обоснована, обязательства указывают на реальные строки.

## Гигиена
- git show --stat ×3: только заявленные файлы; объединённый diff db2b7044..20bc0dc3 не задевает initreply-l1d и чужие слайсы. Гейты plan ×3 воспроизведены: EXIT 0 (148/79/0; 246/47/0; 26/16/0). В cfg-карте семантически изменились ровно 4 строки CFG-02A (RFL→VERIFIED); 34 новых tails-r1 evidence-записи — artifact_sha256 валидны.

## Инцидент-оценка (stale artifact_sha256)
- 52 устаревших sha в cfg-карте — ПРЕДСУЩЕСТВУЮЩИЙ долг (те же sha уже записаны в db2b7044), указывают на «живые» тест-файлы, легитимно изменённые после записи. На поведение поезда 2.58.110 не влияет → отдельная техдолжница: один ограниченный проход перебиндинга sha/пинов к неизменяемым run-артефактам. Не блокирует.

## Неблокирующие замечания
1. asap8 README/V02-observation «capture 4/4»: сырой артефакт показывает indirect_style captured=false (3/4 сценариев; 4 извлечённые строки, dont_repeat держит 2; format.lists_no лежит в сценарии dont_repeat, а README атрибутирует его indirect_style). Суть V02 доказана тем же артефактом — поправить формулировку/атрибуцию (RELATED_SMALL, 1 файл).
2. REQ-B11-E2E: невекторная staging-проверка выполнима агентом до деплоя — классификация RFL неточна (честно раскрыто).
3. Заголовки-контейнеры cfg/p0b оставлены PENDING вместо context (в asap8 переклассифицированы) — косметика реестра.
