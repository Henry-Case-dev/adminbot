# ADR-1020-9 (ui-rework) — пересборка Liquid Glass / Grid / маски секретов / фона / sticky-панели

- **Статус:** ACCEPTED (Шаг 2, Architect)
- **Контекст:** UPD3 `plans/current_task.md:365-403`; провал БЛОК 3 эпика 10.20 (`plans/archive/round1020-lore-compiler-rag-refactor/spec.md:389-455`).
- **Ограничение:** только фронтенд (`web/index.html`, `web/app.js`, `web/static/app.css`) + тесты. R17/R18 — секреты не раскрывать.
- **Связанные:** ADR-1016-2 (self-host/CSP, предсобранный Tailwind), ADR-1020-8 (Справка).

## Контекст решения

Тесты раунда проверяли **наличие строк** (`.glass-bg`, `backdrop-filter: var(--glass-blur)`), а не эффективный результат: `tests/test_webapp_round1020_ui.py:152-172`, `tests/js/round1020_ui_test.js:435-439`. Вдобавок JS-тест прямо фиксировал «секрет НЕ префиллится» (`round1020_ui_test.js:120-122`). Как следствие — неработающее стекло, одноколоночная «ИИ», пустые Betterstack-поля прошли ревью и живой приёмки (T-1904 остался `⏸`).

## Решения

### D1. Liquid Glass — расширить селекторы и убрать solid-конфликт
- Единый «glass set»: `.card` (**94 вхождения**), `.modal-card`, `.module-card`, `.hub-card`, `.prov-block`, `details.advanced`, `.scope-panel`, `.glass-panel`, `.oversight-panel`; alpha `rgba(20,25,30,0.5)`, `blur(16px)` (T-1934).
- Grid-контейнеры `.module-list`/`.hub-grid` (+ новый `.prov-grid`) **исключаются** и обнуляются (`background:transparent;border:0;backdrop-filter:none`) — стекло на карточках, а не на обёртке (T-1934).
- Из всех 5 модалок удаляется `card-solid` (сейчас: `index.html:746,1259,1311,1452,2658`) — класс противоречит заявленному стеклу. Выбор ровно один из двух (T-1933): **убираем из разметки**, а не «override поверх solid».
- `@supports not (backdrop-filter)` → `--glass-bg-strong: rgba(20,25,30,0.85)` вместо `rgba(22,22,22,0.92)` — «плотный фон» сохранён (T-1934).
- `.glass-panel` на «Сводке» сохранён (`index.html:975`); мёртвый `.oversight-panel` остаётся в наборе для совместимости (в разметке отсутствует — зафиксировано в `ui-contract.md`).
- **Почему не Tailwind:** предсобранный `vendor/tailwind.css`, без `!important`/layers; `bg-*` на карточках/модалках отсутствуют — utility-override **не** является причиной (ревизия `web/index.html`).

### D2. Единый grid-контейнер для «ИИ»
- Вводится `.prov-grid` = `display:grid; grid-template-columns:repeat(auto-fit,minmax(320px,1fr)); gap:1rem` — применяется к ветке `llm_providers` (`index.html:214`).
- `.module-list`/`.hub-grid` приводятся к тем же параметрам (было 300px/.75rem).
- С `.prov-block` снимается `max-w-3xl` (иначе трек 768px → фактически 1–2 колонки).
- Мобильное `1fr` (≤479px) сохраняется.

### D3. Маска секретов — значение-сентинел, а не placeholder
- Вводится `SECRET_MASK = '••••••••••••'` + `isSecretMask(v)`.
- **Оба пути:** `blockFieldValue` (`{configured:true}` → маска) для provider-блоков и `_seedSecretMasks()` для `keyDrafts` (generic config / модалка модуля).
- Маска — **не** значение: исключается из `dirtyKeyItems`/`blockDrafts`, блокируется в `saveKeyItem`/`saveBlock`, не попадает в `POST /api/config` (риск R31/R-UI-3).
- Пусто — только при `null`/`{configured:false}` (INV-3 §3.2 spec).
- **Альтернатива (отклонена):** подставлять реальный секрет в инпут — запрещено R17 (`web/api/routes.py:231-240` никогда не отдаёт значение).
- **Альтернатива (отклонена):** оставить только placeholder + бейдж — именно это и привело к «полям пустым» (generic-модалка `index.html:798-807` вообще без бейджа).

### D4. Градиент — оранжевый токен + единый `--grad-speed:6s`
- Добавляется `--grad-d:#FF8A3D` (оранжевый) и `--grad-speed:6s` (14s→6s, 5–8 s) — единый токен на wash и акценты (T-1937).
- Осознанно принимается ускорение `.grad-band`/`.btn-accent`/`.tab-btn.active` до 6s (14s воспринималось владельцем как «мёртвое»); `prefers-reduced-motion` гасит.
- Wash переводится на `conic-gradient(from var(--grad-angle))` + вращение угла → переливы явно видны; `opacity` .16 → ≈.42.
- Следствие: 3 теста-ассерта `--grad-speed:14s` / `grad-drift 18s` обновляются осознанно (§7.4 spec).
- `html` получает базовый цвет, `body` — прозрачный, `#app` — `z-index:1`; так wash гарантированно под контентом и является backdrop'ом для blur.
- `prefers-reduced-motion` и `prefers-contrast` — обязательны.

### D5. Betterstack-логин НЕ десекречивается
- `CHECKUP_BETTERSTACK_SQL_USER` остаётся `secret=True` (`services/param_catalog.py:503`): это половина credential-пары с паролем; десекречивание вернуло бы значение в браузер.
- Требование владельца «не пусто» удовлетворяется маской (§3.2 spec).
- Бэкенд/каталог/формат `/api/config` **не меняются** — иначе расширяется поверхность R17 и всплывают RBAC-нюансы.
- Если владелец захочет видеть логин открыто — отдельная задача с явным security-ревью (упомянуто в рисках R-UI-7).

### D6. Sticky-панель — sticky, но внутрь скролл-контейнера
- Сохраняем `position:sticky;bottom:0` (T-1938), но `<sticky-save>` переносится **внутрь** скроллера: в модалке — последним ребёнком `.modal-body` (сейчас лежит снаружи, в `.modal-footer` → не липнет/всплывает).
- Модалка → flex-колонка (`max-height:min(90dvh,46rem)`), `.modal-body` — единственный скроллер, `.modal-footer` — только «Закрыть».
- Панель остаётся в потоке в конце контента: на максимальном скролле последнее поле видно (постоянного перекрытия нет); `scroll-padding-bottom`/`padding-bottom` ≥ `--sticky-save-h` защищают фокус/`scrollIntoView`.
- Плотный фон `--glass-bg-strong` (.85) + `padding-bottom: calc(.6rem + env(safe-area-inset-bottom))`.
- Вкладки: `:has(> .sticky-save)` + `@supports not (selector(:has(*)))` фолбэк с безусловным `padding-bottom`.
- Inline `max-height:80dvh/70dvh` удаляются из 5 `.modal-body`; досье-футер (`index.html:2694`) переносится внутрь `.modal-body`.

### D7. Feature Flags / Progressive Delivery
- Серверный фича-флаг **не вводится**: он не может управлять CSS-каскадом, только добавит связанность и точку отказа. Релевантные «user-level» деградации: `prefers-reduced-motion`, `prefers-contrast`.
- Откат — атомарный `git revert` (миграций и контрактов нет).

## Последствия
- **Плюс:** дефекты закрываются в корне; тесты становятся каскад-ориентированными; эффект «стекла» становится проверяемым.
- **Минус/осознанное:** правки затрагивают общий `.card`, что меняет вид **всех** карточек и требует визуальной приёмки (§7.5); часть «чужих» тестов придётся обновить (§7.4) — это санкционированный Δ, перечисленный построчно.
- **Обязательство:** Reviewer-протокол §8 (серверный артефакт → каскад → отсутствие override → маска → grid → sticky → gradient → регресс → R18).
