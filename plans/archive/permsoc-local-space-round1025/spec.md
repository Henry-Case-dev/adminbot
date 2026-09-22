# F7 `permsoc-local-space-round1025` — локальная спецификация (Step 2 @Architect)

> **Раунд:** 10.25, Эпик 1, **Волна 3**, шаг 2. **Приоритет:** P0. **Тип:** UI + backend (серверная поддержка отключения).
> **Задачи:** **T-2921…T-2963 (43)** — `tasks.md` (Step 1 @PM, 23.09.2026).
> **Мастер-ТЗ:** `plans/current_task.md` **§60–§67** (+ смежные §70/§71/§73/§74). Файл **untracked** — не коммитить, не изменять; значения/секреты не цитировать (R17/R18).
> **ADR:** `adr-1025-20-permsoc-local-space-and-server-gates.md` (решения D1–D7, AMEND/REUSE-карта).
> **Зависит от:** F1 (IA/`#/permsoc`, ADR-1025-1), F3 (scope/`scopeEpoch`/§43, ADR-1025-10), F4 (store §37–§42, ADR-1025-14), F0 (`persistItems`/409, ADR-1025-2). **От F7 зависят:** F9, F11 (шаблоны вкладок), F10.
> **Статус:** 🟦 **Step 2 @Architect — выполнено (23.09.2026).** Код **не изменялся**. Созданы `spec.md` + **ADR-1025-20**; решения (a)–(g) закрыты; `tasks.md` сверен (§13).
> **Baseline (Step 0 @Memory, принят как данность):** HEAD `551847d` (= `origin/master`), `APP_VERSION` **2.58.14**, pytest **8334/1-skip/5-env**, JS **37/37**, каталог **459/418/434/98/96/21**, SQLite **v12** (**Δ DDL = 0**).

---

## 1. Цель, объём и исключённый объём

**Цель.** Привести вкладку `#/permsoc` к **локальному пространству чата** (§60): сверху «PERMsoc · Только этот чат» + канонический `chat_id`; **6 функциональных блоков** (Славик, Костик, Оля, Мимикрия, Общие реакции, Расписания) с иерархией **мастер → блок → функция** (§61); каждый блок — Название/Описание/Состояние/Переключатель (если сервер умеет)/Настройки. Устранить дефект правки **глобальных** значений при отсутствии выбранного чата (`web/index.html:1294-1298`). Серверно обеспечить **реальное** отключение «Общих реакций» и «Расписаний» (goodmorning) — сейчас у них нет per-chat гейта.

**В объёме F7:**
- Scope-заголовок §60 + `chat_id` в конвенции `.scope-tech`; reuse `scopeEpoch`/F3 (второй селектор **не** создаётся);
- запрет записи PERMsoc-ключей в **global**; поведение «нет выбранного чата» = **не показывать редактируемые блоки** (banner «Выбери чат», не «Без чата меняются только общие значения ниже»);
- `PERMSOC_OWNER_BLOCKS` 5 → **6**; partition «каждый ключ §62–§67 ровно в одном блоке»; «Общее» перестаёт быть свалкой (мастер — отдельный уровень §61);
- **OFF блока сохраняет дочерние значения** (одна мутация на переключение, только собственный ключ блока);
- **отсутствие декоративных тумблеров**: там, где сервер не умеет — тумблер не показывается/помечается; где нужно — **новая серверная доработка** (D3);
- честное derived-состояние (master/block/eff override);
- содержание §62–§67 (группы, русские названия, типы, deprecated, единицы);
- тесты §60–§67/§70/§71/§73/§74; bump `APP_VERSION` 2.58.14 → **2.58.15**.

**Исключено (не делать в F7):**
- **Δ DDL = 0** (серверную схему/SQLite-миграции **не менять**), **Δ каталога = 0** (новых `ParamSpec`/`GroupSpec` нет — только presentation-группировка в JS);
- перенос PERMsoc в **глобальные** настройки (§4/§60) — запрещено;
- второй селектор области, второй write-path, второй store/save-бар;
- изменения §62–§65 `ARCHITECTURE.md` (shell/glass/aurora/flex/heartbeat), F1/F4/F5/F6, ADR-1024-24;
- переписывание `PermsocGateFilter`/мастер-контракта `PUT /api/chat/{id}/gates`;
- Эпик 2/3.

---

## 2. Зафиксированные факты (проверено по коду; строки — ориентир, символы важнее)

| # | Факт | Источник |
|---|---|---|
| Ф1 | In-tab разметка: `PERMSOC_OWNER_BLOCKS` — **5** блоков (slavik/kostik/olya/mimic/common); `<summary>` = единственный тумблер; `PERMSOC_TOGGLE_KEYS` (5 ключей) | `web/app.js:827-861` |
| Ф2 | Рендер: `_permsocOwnerGroups:7146` (ownerOf: `keys` → приоритет, `groups` → остаток; `common` = остаток), `_ownerDescription:7185`, `permsocOwnerOn:7197`, `canToggleOwner:7207`, `toggleOwner:7216` | `web/app.js:7143-7231` |
| Ф3 | Шаблон: `<component :is="grp.owner ? 'details' : 'div'">`, `web/index.html:1264-1313`; **дефект**: `:1294-1298` при `!isChatContext()` сообщает «Без чата меняются только общие значения ниже» | `web/index.html:1264-1313` |
| Ф4 | Мастер: `togglePermsoc:3974` → `toggleGate('permsoc')` → `PUT /api/chat/{id}/gates`; чтение `loadGateInfo:3741` → `GET .../gates`; derived `permsocMasterOn:3984`, `permsocModuleBadge:3991-4004` (alan → `derived (master)`) | `web/app.js:3741-4004`; `web/api/gates.py:49-132` |
| Ф5 | `gates_put`: global admin — любые; local admin — только `HEAVY` (dream/nostalgia/lore_auto); `permsoc` — **только global admin** (403); feature ∉ `ALL_GATED_FEATURES` → 422; 409 optimistic | `web/api/gates.py:89-132`; `services/feature_gates.py:27-31` |
| Ф6 | `ALL_GATED_FEATURES={dream,nostalgia,lore_auto,permsoc}`; `HEAVY={dream,nostalgia,lore_auto}`; `DEFAULT_BY_FEATURE[permsoc]=False`; `gates_enabled` fail-open → глобальный флаг/дефолт | `services/feature_gates.py:26-160` |
| Ф7 | `PermsocGateFilter(module_id)`: master (`gates.permsoc` → `overrides['flags.permsoc_enabled']` → `hot.get(...)`, дефолт `False`) + суб-флаг модуля (`DEFAULT_SUB_FLAGS`: slavik/kostik=True, olya/mimic=False); fail-open OFF; `module_enabled` для `alan` → `True` (нет суб-флага) | `services/permsoc.py:34-168` |
| Ф8 | Фильтр подключён: `slavik.py:172`, `kostik.py:57`, `alan.py:122`, `alan_greeting.py:90/126`, `olya.py:26`, `common.py:242` (mimic) | `handlers/*` |
| Ф9 | **НЕ гейтированы**: `war_alert.py:116/163`, `common.py:61/92/123/154` (otboy/danger/selfdev/work), `vasya.py:23/33`, `slavik.py:153` (kucha) | `handlers/*` |
| Ф10 | `handlers/alan.py:138-143` после гейта читает `flags.alan_replies_enabled` через `hot.get` (**глобально**, без чата) | `handlers/alan.py:138-143` |
| Ф11 | goodmorning — **процессный**: `bot.py:729-734` читает `reactions.goodmorning_*` (fallback `settings.GOODMORNING_*`) при старте; `GoodmorningSchedulerService._tick` шлёт по `GOODMORNING_TARGET_CHAT_IDS` **без per-chat гейта** | `bot.py:727-736`; `services/goodmorning_scheduler.py:95-101`; `services/goodmorning_relay.py:115` |
| Ф12 | Каталог TAB_PERMSOC: категории reactions (12 групп) / flags (`flags_permsoc`,`flags_media`,`flags_permsoc_behavior`) / limits (`limits_alan`,`limits_kostik`,`limits_media_permsoc`,`limits_mimic`,`limits_deadpage`) | `services/param_catalog.py:2191-2203` |
| Ф13 | Группы **смешивают блоки** и требуют key-level владения: `limits_media_permsoc` = GIF/SLAVIC_PHOTO_INTERVAL (Славик) + OLYA_COOLDOWN (Оля) + COMMON/DANGER/SELFDEV/WORK_COOLDOWN (§67); `limits_mimic` = MIMIC_* (Мимикрия) + SLAVIK_MIMIC_* (Славик); `flags_media` = OLYA_CAPTION_* (Оля) + MIMIC_FORWARDS (Мимикрия) + COMMON_MEDIA/COMMON_WORK_MEDIA (Общие реакции); `reactions_slavik` = 2 контент + `slavic_photo_path` (Доп.) | `services/param_catalog.py:989-1013`, `:875-912`, `:1483-1492` |
| Ф14 | `kostik_reply_probability`: сервер **float 0.0–1.0** (1.0 → на каждое; 0.0 → никогда) | `handlers/kostik.py:9-11,63-69` |
| Ф15 | `reactions.slavic_photo_path` **читается** (legacy fallback одиночного фото) — **не удалять** | `handlers/slavik.py:256-257` |
| Ф16 | `reactions.vasya_enabled` существует (кейс `VASYA_ENABLED`, группа `reactions_word_reactions`) и читается | `services/param_catalog.py:1505-1506`; `handlers/vasya.py:26/36` |
| Ф17 | Per-chat запись `/api/config` требует **каталожный** ключ `spec.per_chat=True` (иначе 422); неизвестный ключ → 422. Произвольный новый ключ per-chat записать нельзя | `web/api/routes.py:604-617` |
| Ф18 | `gates` — **не каталог**: значения хранятся в `chat_params["gates"]`; запись через `set_feature_gate` (история + NOTIFY + 409). Новый feature-id = серверная правка **без** Δ DDL/каталога | `services/feature_gates.py:163-187`; `services/chat_params.py` |
| Ф19 | §62 называет `reactions.dead_page_media_dir`, фактический ключ каталога — `reactions.dead_page_dir` (`DEAD_PAGE_DIR`) | `services/param_catalog.py:1471-1472` |

> Карта @Memory (Step 0) подтверждена; уточнения: (Ф13) группы каталога требуют **key-level** владения; (Ф15) deprecated-ключ **живой**; (Ф17) произвольные per-chat ключи невозможны → новые гейты только через `gates`.

---

## 3. D1 — Локальный scope и канонический `chat_id` (§60)

### 3.1. Заголовок и источник чата
- Сверху вкладки — заголовок **«PERMsoc · Только этот чат»** и выбранный чат из F3-scope; полный `chat_id` — в конвенции **`.scope-tech`** (технические подробности), **не** вместо названия (§5).
- Единственный источник `chat_id` = `this.activeChatId` (F3); **повторный селектор не создаётся** (ADR-1025-10). При смене чата вкладка перерисовывается через `scopeEpoch` (`_permsocOwnerGroups`/`permsocOwnerOn` реактивны к scope).

### 3.2. Поведение без выбранного чата — **не править глобал**
- Если `activeChatId == null` (scope = «Глобально») — блоки и тумблеры **не рендерятся**; показывается честный empty-state: «PERMsoc работает только для конкретного чата. Выбери чат или ЛС в шапке.»
- Текст `web/index.html:1294-1298` («Без чата меняются только общие значения ниже») **удаляется** — он противоречит §4/§60.
- **Защита на запись:** `persistItems`/`saveConfigItem` получает guard: попытка записать PERMsoc-ключ (набор из §4 ниже) при scope=global → запись **не выполняется** (ban + toast/лог). Это ловит любой обход UI.
- ЛС: PERMsoc в DM не целевая область (матрица `canViewTab`); поведение «нет чата» покрывает и этот случай.

### 3.3. Разведение контрактов: мастер-гейт vs per-chat override
| Слой | Что это | Хранилище / API | Кто пишет | UI |
|---|---|---|---|---|
| **Мастер `permsoc`** | Глобальный админский рубильник **плагина персонажей** (Славик/Костик/Оля/Мимикрия + Леха) | `chat_params["gates"]["permsoc"]`; `PUT /api/chat/{id}/gates` (Ф4/Ф5) | **только global admin** (403 иначе) | отдельный уровень §61; read-only для не-global-admin |
| **Per-chat override** | Значение ключа только для этого чата | `chat_params["overrides"][key]`; `POST /api/config` c `X-Chat-Id` (F0/F4) | по RBAC `canEditConfig` | «Источник: PERMsoc»; **«Вернуть глобальное» = DELETE override** (F3, не заводской сброс) |
| **Per-chat block-gate** (новое, D3) | Блок «Общие реакции» / «Расписания» | `chat_params["gates"]["permsoc_reactions"|"permsoc_schedule"]`; `PUT /gates` | global admin (как мастер) | тумблер блока; read-only для не-global-admin |

- Мастер **не** равен per-chat override: разные пространства (`gates` vs `overrides`), разные API, разные RBAC — не смешивать.
- Локальные значения **не** перезаписываются глобальными; смена глобального не сбрасывает override (F4 §60.7).

---

## 4. D2 — Шесть блоков: точные границы (§60/§61)

**Правило владения.** Для каждого блока задан **явный список ключей** (`keys`, приоритет); `groups` — только добор невзятых ключей. Каждый ключ TAB_PERMSOC попадает **ровно в один** блок или на мастер-уровень. «Общее/Мастер» **не** собирает остаток (§60: вкладка не свалка).

**Мастер-уровень (не блок):** `flags.permsoc_enabled` (тумблер `gates.permsoc`).

| Блок | Тумблер | Группы (витрина, JS) | Ключи (точно) |
|---|---|---|---|
| **Славик** | `flags.slavik_enabled` | Основное / Контент / Мимикрия / Ограничения / Дополнительно | О: `reactions.slavik_user_id`; К: `reactions.dead_page_relay_channel_id`, `reactions.dead_page_source_channel_id`, `reactions.dead_page_source_channel_username`, `reactions.dead_page_dir`, `reactions.slavic_random_dir`, `reactions.gif_path`; М: `limits.slavik_mimic_cooldown`, `limits.slavik_mimic_min_words`; Огр: `limits.gif_interval`, `limits.slavic_photo_interval`, `limits.dead_page_cooldown`, `limits.dead_page_caption_max_chars`, `limits.dead_page_max_forward_retries`; Доп: `reactions.slavic_photo_path` (**deprecated**) |
| **Костик** | `flags.kostik_enabled` | Основное / Ответы / Ограничения | `reactions.kostik_user_id`, `reactions.kostik_replies` (строки), `limits.kostik_reply_probability` |
| **Оля** | `flags.olya_enabled` | Основное / Источники / Ответы / Ограничения | О: `reactions.olya_user_id`; И: `reactions.olya_saveasbot_channel_ids`, `reactions.olya_saveasbot_user_ids`; Отв: `reactions.olya_media_base`, `reactions.olya_caption_text`, `reactions.olya_media_type`, `flags.olya_caption_enabled`, `flags.olya_repost_enabled`, `flags.olya_always_send`, `flags.olya_caption_mention_enabled`; Огр: `limits.olya_cooldown` |
| **Мимикрия** | `flags.mimic_enabled` | Кого/Реакции/Пересланные/Пауза/Длина | `reactions.mimic_victim_user_ids`, `reactions.alan_mimic_enabled`, `reactions.kucha_enabled`, `flags.mimic_forwards_enabled`, `limits.mimic_cooldown`, `limits.mimic_min_words` |
| **Общие реакции** | `gates.permsoc_reactions` (**новый**, default ON) | Приветствия / Оповещения / Триггеры / Медиа | Пр: `reactions.alan_user_id`, `reactions.alan_username`, `reactions.alan_greeting_dir`; Оп: `reactions.war_channel_ids`, `reactions.war_channel_usernames`, `reactions.war_replies`; Тр: `reactions.danger_words`, `reactions.vasya_enabled`, `flags.alan_replies_enabled`, `flags.dead_page_post_on_join`, `reactions.admin_user_id`; Мд: `reactions.common_media_base`, `flags.common_media_enabled`, `flags.common_work_media_enabled` |
| **Расписания** | `gates.permsoc_schedule` (**новый**, default ON) | Рассылка / Медиа / Доп. ограничения (§67) | `reactions.goodmorning_time`, `reactions.goodmorning_media_dir`, `reactions.goodmorning_target_chat_ids`, `reactions.goodmorning_tz`; Доп: `limits.alan_reply_interval`, `limits.alan_greeting_cooldown`, `limits.alan_silence_greeting_hours`, `limits.danger_cooldown`, `limits.selfdev_cooldown`, `limits.work_cooldown`, `limits.common_cooldown` |

- **§67-лимиты → «Расписания»** (буквально по ТЗ §67 «Дополнительные ограничения»): это **тайминги/кулдауны** («когда»), а «Общие реакции» — идентичности/фразы/медиа/тумблеры («что/кому»). Основание — прямая буква §67; альтернатива (оставить в «Общих реакциях») отклонена, чтобы не спорить с ТЗ и сохранить правило «ключ ровно в одном блоке».
- **`reactions_admin` (ADMIN_USER_ID)** и **`reactions_word_reactions` (VASYA_ENABLED)** → «Общие реакции → Триггеры» (Vasya-реакция использует ID админа); в §62–§67 явно не названы — принято как остаток-в-блоке по функциям, не в «Общее».
- **`reactions_permsoc`** (`alan_mimic_enabled`, `kucha_enabled`) → **Мимикрия** (§65, явные ключи), не «Общие реакции».
- **§62 `dead_page_media_dir`** = фактический `reactions.dead_page_dir` (Ф19) — в UI подпись «Папка медиа dead page».
- **OFF блока сохраняет дочерние** (§61): тумблер блока пишет **только** `owner.toggleKey` (персональные — `saveConfigItem`; новые — `toggleGate`) — ни один дочерний ключ не сбрасывается/не удаляется. Отдельный тест «вкл→выкл → дочерние байт-в-байт».
- **Нет декоративных тумблеров** (§61): тумблер показывается только там, где есть реальный серверный путь (D3). Если у блока/функции эффекта нет — тумблер не показывается или помечен «не поддерживается».
- **Derived-состояние** (честно, без выдумок): персональные блоки = `master AND sub_flag` (`OFF (master)` при master OFF); **«Общие реакции»/«Расписания» не зависят от мастер-плагина** — у них собственный блок-гейт (D3). Это сознательное решение (см. ADR-1025-20 D2/D3): распространение мастер-плагина на ранее **негейтированные** war/danger/goodmorning молча выключило бы живые функции (master default `False`) → регрессия, запрещённая приоритетом №1 ТЗ.

---

## 5. D3 — Серверная поддержка отключения (§61)

### 5.1. Фактический источник состояния по блокам (матрица «блок → где отключается»)

| Блок | Тумблер (запись) | Реальный рантайм-эффект | Статус |
|---|---|---|---|
| Славик | `flags.slavik_enabled` (override) | `PermsocGateFilter("slavik")` (master + суб-флаг) | ✅ есть |
| Костик | `flags.kostik_enabled` | `PermsocGateFilter("kostik")` | ✅ есть |
| Оля | `flags.olya_enabled` | `PermsocGateFilter("olya")` | ✅ есть |
| Мимикрия | `flags.mimic_enabled` | `PermsocGateFilter("mimic")` (`common.py:242`) | ✅ есть |
| **Общие реакции** | `gates.permsoc_reactions` (**new**) | **нет** для war/danger/otboy/selfdev/work/vasya/kucha; alan — master-only (`alan_replies_enabled` — глобальный `hot.get`, Ф10) | ⛔ **пробел → закрыть** |
| **Расписания** | `gates.permsoc_schedule` (**new**) | goodmorning — процессный, **без per-chat гейта** (Ф11) | ⛔ **пробел → закрыть** |

### 5.2. Решение: новый per-chat блок-гейт через `feature_gates.gates` (**Δ DDL = 0**, без новых таблиц/каталога)
- В `services/feature_gates.py`: `ALL_GATED_FEATURES` += `{"permsoc_reactions", "permsoc_schedule"}`; `DEFAULT_BY_FEATURE` для них = **True** (нет явного гейта → функция работает — **сохраняет baseline**, не регрессирует); `MASTER_FALLBACK_KEYS` не трогаем. `FLAG_KEYS` для них — пусто (работает только явный `gates` + дефолт).
- В `services/permsoc.py` (расширение существующего модуля, **не** второй плагин): `async def block_enabled(chat_id, block_id) -> bool` — для `reactions`/`schedule` читает `gates_enabled(chat_id, "permsoc_<block>")`; при исключении → `False` (**fail-open OFF** — безопасная тишина, как у `master_enabled`). Новый `BaseFilter PermsocBlockGate(block_id)` — для ранее негейтированных хендлеров; он проверяет **только** блок-гейт (мастер к новым блокам не применяем — см. D2/ADR).
- Рантайм-точки (единый проброс `chat_id`):
  - `handlers/war_alert.py:116` и `:163` → `PermsocBlockGate("reactions")`;
  - `handlers/common.py:61/92/123/154` (otboy/danger/selfdev/work) → `PermsocBlockGate("reactions")`; `:242` (mimic) уже под `PermsocGateFilter("mimic")` — **не трогаем**;
  - `handlers/vasya.py:23/33` → `PermsocBlockGate("reactions")`;
  - `handlers/slavik.py:153` (kucha) → `PermsocBlockGate("reactions")` (сохранить `reactions.kucha_enabled`);
  - `handlers/alan.py:122`, `handlers/alan_greeting.py:90/126` → **добавить** `PermsocBlockGate("reactions")` к существующему `PermsocGateFilter("alan")` (master остаётся);
  - dead-page join (`dead_page_trigger.py`, флаг `flags.dead_page_post_on_join`) → `PermsocBlockGate("reactions")` (если ветка постит из общего пути).
- **goodmorning**: `GoodmorningSchedulerService._tick` перед `relay.send_goodmorning(chat_id)` проверяет `await permsoc.block_enabled(chat_id, "schedule")`; при OFF — `continue` + `logger.info(... skipped ...)`, **без отправки**. «Фоновая задача прекращается» для отключённого чата — поведенчески проверяемо (мок relay: `send` не вызван).
- **RBAC/честность**: `gates_put` для `permsoc_reactions`/`permsoc_schedule` остаётся global-admin (как `permsoc`); `gates_get.who_can_toggle` для всего семейства `permsoc*` = `"global"` (Ф5-фикс, чтобы UI не обещал локальному админу невозможное). `canToggleOwner` для новых блоков = `isGlobalAdmin` → у остальных тумблер read-only с подписью.
- **fail-open OFF**: и мастер, и блок-гейты при недоступности PG/кэша → `False` (молчание), без спама (WARNING).
- **Совместимость**: существующие вызовы `PermsocGateFilter` не меняются; `gates_enabled` — аддитивно; `auto_opt_in` не срабатывает (фичи ∉ HEAVY); серверная семантика `override → global → default` и единицы не меняются (§74/§59).

---

## 6. D4 — Содержание блоков §62–§67

- **§62 Славик:** группы Основное/Контент/Мимикрия/Ограничения/Дополнительно; `reactions.slavik_user_id`; контент (см. §4, `dead_page_*` + `slavic_random_dir` + `gif_path`); мимикрия (`slavik_mimic_cooldown/min_words`); ограничения (`gif_interval`, `slavic_photo_interval`, `dead_page_cooldown`, `dead_page_caption_max_chars`, `dead_page_max_forward_retries`); Дополнительно — `reactions.slavic_photo_path` (**deprecated, видим, НЕ удалять**; код его ещё читает — Ф15), подпись «(deprecated)» с пояснением.
- **§63 Костик:** `reactions.kostik_user_id` («Telegram ID Костика»), `reactions.kostik_replies` («Фразы Костика») — **построчный редактор** (виджет `list`): каждая фраза — строка; сохранение — один key, список без потери пустых/дублей молча; парсер сервера `_resolve_replies` принимает list/JSON-строку (Ф14) — формат не ломаем. `limits.kostik_reply_probability` («Вероятность ответа») — **сервер float 0.0–1.0**; UI = **проценты 0–100 %**; конвертация на границе виджета (`p=percent/100`, `percent=round(p*100)`), клип [0,1]; границы 0/1 (=0/100 %) корректны; round-trip-тест.
- **§64 Оля:** группы Основное/Источники/Ответы/Ограничения; ключи по §4; **списки ID** (`olya_saveasbot_channel_ids`, `olya_saveasbot_user_ids`) — структурированно (чипы/строки, `widget=list`), не сырой CSV.
- **§65 Мимикрия:** 6 ключей + русские названия ТЗ («Кого передразнивать», «Мимикрия Лёхи», «Реакция на триггерную фразу», «Мимикрия пересланных сообщений», «Пауза между передразниваниями», «Минимальная длина сообщения»); не пересекается с «Общими реакциями»/Славиком.
- **§66 Общие реакции:** ключи по §4; группы Приветствия/Оповещения/Триггеры/Медиа; `reactions.vasya_enabled` существует (Ф16).
- **§67 Расписания:** `goodmorning_*` + доп. ограничения (по §4). **Единицы (серверные не меняем, §59-прецедент):** `goodmorning_time` = `HH:MM` 24ч; `goodmorning_tz` = IANA-зона (валидация `ZoneInfo`, невалидная → fallback `Asia/Yekaterinburg`, как сейчас); `goodmorning_target_chat_ids` = JSON-массив int; `goodmorning_media_dir` = путь; `alan_reply_interval` = **сообщения** (int); `alan_greeting_cooldown` = **сек** (int); `alan_silence_greeting_hours` = **часы** (float); `danger/selfdev/work/common_cooldown` = **сек** (float). Подписи единиц — из существующих заголовков каталога (менять не нужно).

---

## 7. D5 — Каталог: presentation-группировка без Δ каталога

- **Δ каталога = 0**: `services/param_catalog.py` **не трогается** (REGISTRY 459 / GROUPS 98 / `_TAB_BY_GROUP` 96 / TAB_RULES 21 / Settings 418 остаются). Все группы §62–§67 уже входят в `TAB_PERMSOC` (Ф12) — добавлять нечего.
- **Владельцы и подгруппы** задаются **в JS** (`PERMSOC_OWNER_BLOCKS` `keys` — key-level владение из-за смешанных групп Ф13; новый JS-константа `PERMSOC_BLOCK_SUBGROUPS` — русские названия/порядок подгрупп внутри блока). Это **витрина**, не каталог (прецедент F4/F5/F6).
- Обоснование, почему без правки каталога: группы `limits_media_permsoc`/`limits_mimic`/`flags_media`/`reactions_slavik` физически смешивают блоки, а любое дробление на уровне `GroupSpec` = Δ каталога (запрещено). Key-level `keys`-приоритет в `ownerOf` (Ф2) уже это поддерживает.

---

## 8. D6 — Инварианты и тесты

**Инварианты (проверяются в диффе/тестами):**
- **Δ DDL = 0** — `services/param_catalog.py` вне диффа; миграции/ALTER/`user_version` не трогаются (остаются v12); новых таблиц/колонок нет.
- **Δ каталога = 0** — счётчики каталога неизменны; новых `ParamSpec`/`GroupSpec` нет.
- **CSP/zero-build** — без CDN/inline/eval/новых библиотек; правки только `web/app.js`/`web/index.html`/`web/static/app.css` (+ серверные гейты).
- **«Локальные не перезаписываются глобальными»**; **«OFF блока сохраняет дочерние значения»**; **«фоновая задача прекращается»** (goodmorning no-send); **«нет записи PERMsoc в глобал»** (нет чата → нет мутаций; guard `persistItems`).
- **Чаты не смешиваются** (§73): stale-ответ чата A не меняет B (F3/F4 `scopeEpoch`/`key`).
- **Не ломать:** §62–§65 ARCHITECTURE (shell/glass/aurora/flex/heartbeat), F0 (`persistItems`/409), F1 (IA/`#/permsoc`), F3 (scope/§43), F4 (store §37–§42), F5, F6, ADR-1024-24.
- **R17/R18**: без секретов/сырых значений; `plans/current_task.md` не изменён/не коммитится; теги/бэкапы/`stash@{0}` целы.

**Тесты (ориентир, детали — `tasks.md` Блоки C/D/E/F):**
- JS: partition-тест «каждый ключ §62–§67 ровно в одном блоке»; `PERMSOC_OWNER_BLOCKS` = 6; мастер-уровень отдельно; OFF блока → дочерние неизменны; нет чата → блоки не рендерятся; «Общее» пусто; конвертация `kostik_reply_probability` round-trip (0/0.5/1 ↔ 0/50/100 %); сохранность deprecated.
- pytest: goodmorning при `gates.permsoc_schedule=false` **не отправляет** (мок relay), ON → baseline; war/danger/vasya/alan при `gates.permsoc_reactions=false` не срабатывают; master OFF → персональные молчат; fail-open OFF; `gates_put/gates_get` для новых фич и `who_can_toggle`; guard «PERMsoc-ключ не пишется глобально».
- UI-матрица (`tools/ui_round1025_matrix.py`): 6 блоков, нет горизонтального скролла, тумблеры ≥44×44 не обрезаны; смена чата A→B→A.

---

## 9. D7 — Kill-switch и bump

- **Kill-switch: ДА** — env-only `ClassVar[bool]` `PERMSOC_BLOCK_GATES_ENABLED` (default **ON**, вне каталога → Δ каталога=0; прецедент `MULTILAYER_EXTRACTION_ENABLED`/ADR-1024-13). OFF → **baseline-поведение**: `block_enabled` всегда `True` (новые гейты не влияют на хендлеры), goodmorning без per-chat проверки; в UI новые тумблеры блоков «Общие реакции»/«Расписания» не показываются как рабочие (честный read-only). Доставка в UI — аддитивно через `GET /api/me.ui_flags` (как F2/hotfix6-9).
- **Мастер-тумблера недостаточно** как kill-switch: он не покрывает новый серверный слой (goodmorning/war/danger) и не может «выключить» уже раскатанное поведение — нужен отдельный рубильник.
- **Bump:** `APP_VERSION` 2.58.14 → **2.58.15** (`config/settings.py`) + cache-bust `?v=__APP_VERSION__` + `README.md` при необходимости.

---

## 10. Трассируемость REQ → решения/задачи

| REQ | §  | Решение | Задачи |
|---|---|---|---|
| R-F7-1 | §60 (локал/`chat_id`) | D1 (canonical `activeChatId`; guard «нет записи в global») | T-2925, T-2926 |
| R-F7-2 | §60 (заголовок) | D1 §3.1 | T-2924 |
| R-F7-3 | §60 (6 блоков) | D2 (6 блоков, partition) | T-2928…T-2931 |
| R-F7-4 | §60 (структура блока) | D2/D4 | T-2929, T-2930 |
| R-F7-5 | §61 (иерархия) | D2 (мастер → блок → функция; честный derived) | T-2932, T-2935 |
| R-F7-6 | §61 (сохранять дочерние) | D2 (одна мутация — только `toggleKey`) | T-2933, T-2952 |
| R-F7-7 | §61 (нет декоративных) | D3 (реальные гейты) + D2 (честные пометки) | T-2934, T-2940 |
| R-F7-8 | §61 (серверная доработка) | D3 (`permsoc_reactions`/`permsoc_schedule`) | T-2937…T-2942 |
| R-F7-9 | §61 (фон прекращается) | D3 (goodmorning `_tick` per-chat) | T-2941, T-2952 |
| R-F7-10 | §62 Славик | D4 (deprecated сохранён) | T-2943, T-2950 |
| R-F7-11 | §63 Костик | D4 (строки; units) | T-2944, T-2945 |
| R-F7-12 | §64 Оля | D4 (списки/группы) | T-2946 |
| R-F7-13 | §65 Мимикрия | D2/D4 (6 ключей) | T-2947 |
| R-F7-14 | §66 Общие реакции | D2/D4 (границы, `vasya`) | T-2948 |
| R-F7-15 | §67 Расписания | D2/D4 (лимиты в Расписания; единицы) | T-2949 |
| R-F7-16 | §73/§74 | D6 (изоляция чатов; семантика) | T-2927, T-2952 |
| R-F7-17 | §70/§71 | D6 (матрица, без скролла/обрезки) | T-2952 |

---

## 11. Открытые вопросы (a)–(g) — закрыты

| | Вопрос | Решение |
|---|---|---|
| **a** | Границы «Общие реакции»/«Расписания»; `word_reactions`/`admin` | §4: все §62–§67 ключи разложены; доп.-лимиты §67 → «Расписания»; `reactions_admin`+`word_reactions` → «Общие реакции/Триггеры»; `reactions_permsoc` → Мимикрия; «Общее» пусто |
| **b** | scope/`chat_id`, поведение без чата | §3: `activeChatId` + `.scope-tech`; без чата блоки **не рендерятся**; текст `:1294-1298` удалён; guard записи; мастер≠override (разные API/RBAC) |
| **c** | goodmorning per-chat | §5.2: `gates.permsoc_schedule` + проверка в `_tick` перед отправкой; Δ DDL=0; «прекращается» проверяемо |
| **d** | Общие реакции (alan/war/common/danger) | §5.2: единый `PermsocBlockGate("reactions")` (расширение `services/permsoc.py`, не второй модуль); fail-open OFF; master default False сохранён; `flags.vasya_enabled` существует (Ф16) |
| **e** | deprecated `slavic_photo_path` | Видим в «Дополнительно» с «(deprecated)»; **не удалять** — код читает (Ф15) |
| **f** | kill-switch | §9: env-only `PERMSOC_BLOCK_GATES_ENABLED` (default ON), OFF=baseline |
| **g** | единицы | §6: `kostik_reply_probability` сервер 0–1 / UI %; `goodmorning_time` HH:MM; `goodmorning_tz` IANA (валидация ZoneInfo); §67-лимиты — сообщения/сек/часы (серверные не меняются) |

---

## 12. Риски и митигации

| Риск | Уровень | Митигация |
|---|---|---|
| Запись PERMsoc в **глобал** (§4/§60) | **Critical** | Без чата блоки не рендерятся + guard `persistItems` + тест «глобальные PERMsoc-значения не меняются» (T-2925) |
| Декоративные тумблеры без эффекта | **High** | Новые гейты D3 (war/danger/vasya/goodmorning) + честная пометка/скрытие (T-2934/T-2940) |
| Сброс дочерних при OFF блока | **High** | Одна мутация только по `toggleKey`; тест «дочерние байт-в-байт» (T-2933) |
| Регрессия: мастер-плагин на негейтированные функции | **High** | Новые блоки **не** зависят от мастера; default ON; ADR фиксирует отклонение от буквы §61 с обоснованием (приоритет №1 ТЗ) |
| Расхождение единиц `kostik_reply_probability`/§67 | **Medium** | Конвертация на границе + round-trip-тест; серверные единицы не меняются |
| `flags.vasya_enabled` «не найден» (карта Step 0) | **Medium** | Ф16: ключ существует (`reactions.vasya_enabled`) и читается — снят |
| Каталог `dead_page_media_dir` отсутствует (есть `dead_page_dir`) | **Low** | Ф19: UI подпись, ключ фактический; каталог не трогаем |

---

## 13. Сверка `tasks.md` ↔ `spec.md`/ADR (для T-2923 @PM)

Расхождений, требующих правки задач, **нет**. Уточнения к формулировкам (не меняют состав T-2921…T-2963):
- T-2938/T-2939: реализация — **новые per-chat блок-гейты** `permsoc_schedule`/`permsoc_reactions` в `feature_gates.gates` + `PermsocBlockGate` в `services/permsoc.py` (**не** второй модуль, **не** Δ DDL).
- T-2930: «принадлежность групп» реализуется **key-level в JS**, `param_catalog.py` не трогается (Δ каталога = 0) — как и требует «Готово, когда».
- T-2953: kill-switch — **вводится** `PERMSOC_BLOCK_GATES_ENABLED` (не «мастер-тумблера достаточно»).
- T-2932: мастер-контракт `PUT /chat/{id}/gates` сохраняется; новые блок-гейты — **тот же** эндпоинт, иные feature-id; `who_can_toggle` для `permsoc*` = `"global"`.
- **§67-лимиты** отнесены к блоку «Расписания» (T-2949) буквально по §67.

---

## 14. Ссылки

- **ADR:** `adr-1025-20-permsoc-local-space-and-server-gates.md` (D1–D7).
- **ТЗ:** `plans/current_task.md` §60–§67 (+ §70/§71/§73/§74).
- **Код:** `web/app.js` (`PERMSOC_OWNER_BLOCKS`/`PERMSOC_TOGGLE_KEYS`/`_permsocOwnerGroups`/`permsocOwnerOn`/`canToggleOwner`/`toggleOwner`/`togglePermsoc`/`loadGateInfo`/`permsocMasterOn`/`permsocModuleBadge`, guard `persistItems`), `web/index.html:1264-1313`, `services/permsoc.py`, `services/feature_gates.py`, `services/goodmorning_scheduler.py`, `handlers/{war_alert,common,vasya,alan,alan_greeting,slavik}.py`, `services/param_catalog.py:2191-2203` (read-only).
- **Архитектура (для Merge §66):** `plans/ARCHITECTURE.md` §57–§65.
