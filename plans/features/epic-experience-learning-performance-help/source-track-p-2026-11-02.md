# Source snapshot — track P (EPIC-EXPERIENCE-LEARNING-ADMIN-PERFORMANCE-HELP)

**Immutable feature source. Do not edit; supersede with a new dated snapshot instead.**

Composite provenance (two independent sources, each reproduced verbatim below):

1. `plans/current_task.md` (user-owned, read-only), sha256 `b7dd0b4a81cc52db851bd41365b8b7a56e70b98e1fde398ce841c4824b112abf`, git HEAD `bab15d68573243fdc1a24fc3286d917d2c60c509` at capture:
   - `§0.3` conflict-table row on line 4073 (the only cross-track clause that binds track P);
   - the complete track `P` section, lines 4198–4278 (P1, P2, P3.1–P3.5, P4 table P-01…P-16,
     Definition of Done P).
2. `plans/owner_inputs/2026-11-02-performance-parity-clarification.md`
   (OI-2026-11-02-PERF-PARITY; orchestrator brief alias: OI-2026-11-02-PERFORMANCE-PARITY), sha256 `9f66be9720084ce685fdb2e4b5244223523c2d4ffc0a59aabac1853474fb823f`, owner amendment body verbatim.

Why composite: newest explicit owner instruction wins, and both texts are binding. The owner amendment
narrows what "optimisation" may do without repealing any measured-performance obligation of the spec, so
neither source may be dropped. Section 2 repeats the amendment text that also lives in the owner-input
file, so this snapshot stays self-contained for gate anchoring; the owner-input file remains the intake
record and the authority if the two ever diverge.

Tracks `E` and `H` are out of scope of this snapshot: they require their own sources/maps. Track `H`
keeps its own execution gate and is only referenced here as a dependency node in `slice-graph.json`.

Anchors in `requirements-map.json` use **snapshot line numbers** (machine-checked by
`requirements_gate.py`). Each row also carries `source_ref` with the original
`plans/current_task.md` line or the owner-input line, so the audit trail stays human-traceable.

---

## 1. plans/current_task.md §0.3 — binding cross-track conflict resolution (verbatim, line 4073)

| «Быстрее админка» vs «сохранить дизайн» | Стиль, графика, стекло и мобильная геометрия сохраняются; оптимизировать путь загрузки и невидимую работу. Декоративное отключение всех эффектов не является исполнением задачи. |

## 2. plans/current_task.md — track P, lines 4198–4278 (verbatim)

# P. Ускорение загрузки и работы админки (Telegram Mini App + desktop)

## P1. Базовая картина и ограничения

На просмотренном публичном `master` обнаружено: `web/app.js` ≈1.30 MiB, `web/index.html` ≈0.89 MiB, `web/static/app.css` ≈245 KiB — **размеры сырых файлов, не сетевой transfer и не доказательство конкретной задержки**; множество синхронно подключаемых vendor-скриптов в `web/index.html`, `app.js` подключается после них; `web/app.py::CacheControlStaticFiles` ставит `no-cache, no-store, must-revalidate` для `.js/.css/.html` несмотря на `?v=__APP_VERSION__`; `/static/app.css` тоже отдаётся с `no-store`. Есть полигональный фон, Aurora/WebGL, Liquid Glass, преломление, Chart.js, длинные API-витрины. Эти точки — кандидаты, не окончательный диагноз. Полный исполняемый `app.js` в доступном коннекторе не удалось раскрыть текстом; Builder проверяет его **на локальной копии проекта**.

Цель — **существенно ускорить фактическое получение полезного экрана, отклик управления, переходы по вкладкам и выбор чата** на Android Telegram WebView и desktop без деградации визуального стиля, приватности и семантики настроек. **Не допускается** принять косметически быстро нарисованный skeleton за готовое приложение или скрыть настоящую задержку за анимацией.

## P2. Сначала измерение, затем правки (это этап реализации, не отдельный аудит)

Для одного зафиксированного исходного SHA и идентичного контрольного окружения:

- **Cold**: новый cache/profile, первый вход в TMA; **warm**: повторный вход с уже прогретыми asset cache, тот же релиз; desktop отдельно. На каждом режиме несколько воспроизводимых запусков; сохранять p50/p95 или точный набор измерений, если выборка мала.
- Navigation TTFB, FCP и LCP при применимости, время до **реального полезного статуса** (не skeleton), до интерактивного первого экрана, отклик кнопки/смены вкладки/чата, long tasks, frame drops, UI responsiveness, network requests, compressed transfer bytes, статусы cache 200/304/memory, main-thread parse/compile/mount и layout.
- Для API: latency на `/config`, status, нужных стартовых endpoint, число SQL и длительность самых дорогих SELECT, размер JSON, N+1, event-loop/CPU. Не выводить секреты/initData в диагностических логах или файлах.
- Отдельно отделять реальные network, server, JS и render задержки. Выявленные изменения связывать с конкретными измерениями, а не приписывать весь выигрыш «оптимизации» вообще.
- Для чистоты сравнения: одинаковый viewport, устройство/эмуляция, версия сети, авторизация, набор данных, вкладка, кеш-состояние, а также version SHA и включённые стеклянные эффекты; не сравнивать холодный до и тёплый после.

Производительность должна улучшиться по **реальным измерениям**. Рекомендуемая инженерная цель — заметное снижение медианного времени до полезного первого экрана и задержки отклика; оценивать также хвост задержек и отсутствие регрессий. Нельзя закрыть задачу за счёт снижения качества/выключения функций. Фиксировать реальные числа до/после; если недоступен настоящий Android WebView, явно пометить, что мобильная проверка не подтверждена, а не симулировать `PASS`.

## P3. Обязательные направления реализации

### P3.1. Доставка JS/CSS/HTML и cache-инвалидация

1. Отделить **меняющийся HTML, приватные API** от **версионированных статических ресурсов**. HTML и авторизованные API не должны кэшировать секреты. Файлы JS/CSS/vendor, имеющие корректную fingerprint/version стратегию, должны эффективно переиспользоваться после повторного открытия.
2. Версия в URL должна реально меняться при изменении байтов; `no-store` для безопасных версионированных ресурсов устранить, применив подходящую браузерную политику (`public/max-age/immutable` только при гарантированной byte-version consistency; иначе корректная ревалидация). Старый WebView после релиза не должен запускать смесь старого кода и нового HTML. Проверить GET/HEAD, ETag, 304, Content-Length, CDN/proxy и разные Telegram WebView.
3. Проверить gzip/brotli для текстовых файлов на реальном пути proxy/ASGI, заголовки `Vary: Accept-Encoding`, ETag и отсутствие double compression. Убедиться, что HTTP size и bytes после сжатия измерены, а не рассчитаны на глаз.
4. Не превращать каждый `<script>` в `async`. Сохранить зависимости Vue, DOMPurify, Telegram bridge, графики и canvas. Синхронный необходимый bootstrap должен быть кратким; всё не обязательное первому экрану — отложить/dynamic-load. Отказы необязательных частей не должны ломать вход.
5. Сохранять текущую CSP без `unsafe-inline`/опасных обходов и прежнюю совместимость с системой деплоя (предпочтительно без новой тяжёлой сборки). Новый framework не нужен; минимальная модульность допустима и должна быть понятна Reviewer/DevOps.

### P3.2. Разгрузка монолитного frontend и первого экрана

6. Разбить тяжёлую шаблонную/вычислительную поверхность на области, создаваемые при реальном открытии. Первая вкладка «Статус» не должна парсить/монтировать все графы памяти, весь редактор промптов, все модалки, Chart.js и все отчёты анализа для скрытых вкладок.
7. Компоненты, таблицы, графики, тяжёлые вычисления и дополнительные CSS/JS для модулей грузить по потребности, с корректными `loading/error/empty/retry`, а не с бесконечными заглушками. Отдельно обеспечить прямой заход на deep link/выбранную вкладку, не только навигацию от «Статуса».
8. Сократить Vue mount/update/избыточные watchers/computed/DOM обходы. Для длинных списков использовать порционную выборку или виртуализацию при сохранении клавиатурной навигации, прокрутки, кликабельных строк и дат.
9. Не нарушать существующее responsive размещение, mobile keyboard, селектор чата, blur/refraction, полноэкранный режим, подтверждение несохранённых изменений, доступность. Внедряемые в `current_task` исправления UI не откатывать ради скорости.

### P3.3. Правильный старт приложения

10. Разделить bootstrap readiness: Telegram init/auth + необходимый набор разрешённых данных для **текущей вкладки** vs вторичные отчёты/другие настройки. Не загружать полную аналитику всех вкладок перед первым полезным экраном.
11. В initial load скелетон, спиннер и полосы прогресса должны означать реальные стадии или быть явно неопределёнными. Для любой стадии есть конечный `loaded`, `empty`, `error/retry` или понятный degraded state. Никакой вечной «Загружаем настройки…» при уже показанной рабочей части.
12. Параллелить **независимые** необходимые запросы; зависимые выполнять в правильном порядке. Схлопывать дубликаты одинаковых GET одного scope. Внешние `retry` не дублируют запись настроек и не отправляют параллельные конфликтующие mutations.
13. При смене выбранного чата/scope устаревший ответ предыдущего запроса не перезаписывает новый: AbortController или request generation + правильная проверка scope/revision; RBAC соблюдается на сервере, не только скрытием элементов.
14. Не создавать второй непрозрачный «умный кеш». Если уместно, использовать локальное scoped memo для read-only данных с точной инвалидацией по изменившемуся ключу/ревизии; при смене пользователя/прав/чата исключить leakage. Не кешировать секреты в persistent browser storage.

### P3.4. Анимации, фон, стекло, геометрия

15. Профилировать `polygon-background.js`, `aurora-flow.js`, `glass-refraction.js`, `glass.js`, `glass-probe.js`, ResizeObserver, rAF, DOM-снимки и canvas buffers на реальных устройствах/вкладках.
16. Сохранять внешний вид; прекращать невидимую непрерывную работу на `document.hidden`, закрытой модалке, скрытом overlay, внеэкранных тяжёлых блоках. При возврате активировать без скачка/потери geometry; избегать двойного рендера нескольких фоновых движков.
17. Группировать чтения DOM геометрии и записи стилей, устранять неограниченные reflow/read/write циклы. Ресайз и скролл не должны провоцировать полный скан всех стеклянных карточек каждую анимационную итерацию.
18. При аппаратной деградации возможно адаптивное разрешение/FPS **на основе измеряемого качества кадров**, обратимо и без `userAgent`-хардкода. Не выключать стекло глобально в «режиме ускорения» ради хороших чисел.

### P3.5. API, SQL, сервер

19. Профилировать `/config` и bootstrap. Реально тяжёлые части полного каталога/permission metadata отделить от начального view, сохраняя единый source-of-truth `param_catalog`, RBAC/effective values и штатные write endpoints.
20. Измерить тяжёлые `/status`, `/oversight`, `/analytics`, память, уроки и другие endpoints при переключениях. Оптимизировать доказанный N+1, повторные SELECT, крупные full-scan/ORDER BY, неподходящие индексы; только после `EXPLAIN` и baseline. Никакой второй таблицы «быстрой истины» без строгой необходимости.
21. Отдавать списки страницами/keyset, а не грузить тысячи строк ради первых нескольких. В UI не подменять отсутствующие данные нулями, не рисовать «успех» при timeout. Логи и trace не должны создавать новый тяжёлый poller.
22. Сохранять event loop отзывчивым: CPU-bound подготовка больших JSON/графов не блокирует жизненно важный status/config. Не маскировать проблему произвольным коротким timeout или длительно удерживаемым глобальным mutex.

## P4. Верификация, отрицательные сценарии, недопустимые «ускорения»

| ID | Проверка | PASS |
|---|---|---|
| P-01 | Cold/Warm Android + desktop до/после | Сопоставимые traces и реальные улучшения, с SHA и условиями. |
| P-02 | Первое открытие «Статуса» | Полезная информация появляется без загрузки скрытой аналитики/редакторов. |
| P-03 | Второй вход после того же релиза | JS/CSS реально переиспользуются безопасным cache; не `no-store` повсюду. |
| P-04 | Новый релиз в Telegram WebView | Установлен новый код без stale mixed assets и принудительной очистки. |
| P-05 | Медленная сеть, отказ API, offline→online | Не застревает на skeleton, ошибки различимы, retry работает. |
| P-06 | Быстро сменить несколько чатов | Нет stale overwrite, утечки данных или неверных настроек. |
| P-07 | Многоразовый переход между вкладками | Нет растущих слушателей, таймеров, canvas и heap. |
| P-08 | Скрыть TMA, затем вернуться | Animation CPU/GPU уходит в idle, затем интерфейс корректно восстанавливается. |
| P-09 | Android keyboard/landscape/fullscreen/dropdowns | Контролы остаются доступными, скролл и геометрия не ломаются. |
| P-10 | Вкладки с большим числом записей | Прокрутка/фильтр/сортировка отзывчивы, строки не теряются. |
| P-11 | Permissions и секретные API | Ничего не обходит RBAC; секреты/initData не кешируются/логируются. |
| P-12 | Внешний вид, стекло и полигональный фон | Эквивалентные скриншоты/видео при включённых эффектах, без «оптимизации удалением». |
| P-13 | Изменение настроек / два администратора | Conflict control и актуальная ревизия работают после кеширования. |
| P-14 | Backend p50/p95/SQL | Измерены реальные изменения и не появились серьёзные регрессии. |
| P-15 | Browser CSP и двойной JS dependency | Никакой регрессии авторизации/загрузки Telegram bridge/Chart/DOMPurify. |
| P-16 | Невозможность реального мобильного прогона | Статус «не проверено» и конкретный blocker, не выдуманный PASS. |

**Definition of Done P:** набор воспроизводимых real traces, конкретный измеренный выигрыш, отзывчивость UI, полный функциональный regression и сохранение визуального качества. Если изменения лишь уменьшают размер bundle, но интерфейс фактически не ускорился, трек P не принят.

---

## 3. Owner amendment OI-2026-11-02-PERFORMANCE-PARITY (verbatim)

optimisation may touch ONLY code, loading, rendering, requests, caching and internal architecture.
Forbidden: changing, simplifying, hiding, disabling, trimming or visually degrading any existing
functionality, UI, animations, glass/refraction effects, background, layout or interaction behaviour.
No lightweight modes, no silent fallbacks, no speed from UX degradation. Only internal optimisation
with FULL visual and functional parity. ANY deviation = regression = release blocker, even if
metrics improve.
