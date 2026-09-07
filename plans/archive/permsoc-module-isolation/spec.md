# Спецификация: PERMsoc Module Isolation (F-9)

**Эпик:** раунд 10 (07.09.2026), часть 2.1 «Multi-chat scaling» (вариант A, research `plans/docs/multi-chat-scaling-research.md` §4, п. 2 профиль нового чата + §5.1). **Задачи:** T-878…T-889 (база HEAD `fac1b9f`).
**Статус:** спецификация @Architect (T-878) — закрывает Q1–Q6 раздела A `tasks.md`. Все обязательные взаимные цепочки с F-7 (`chat_params`, RBAC), F-10 (stорa gates), F-11 (TMA-навигация), F-12 (oversight) — см. §3 §6.

---

## 1. Скоуп и инварианты

**Проблема:** 5 hardcode-триггеров персон (Славик `479167456`, Костя `350803143`, Леха/Алан `138811255`, Оля `834424825`, передразнивания/mimic) срабатывают в КАЖДОМ чату, куда добавлен бот, без управления. Нужно: единый плагин «Функции PERMsoc» с master-тумблером, по умолчанию OFF для новых чатов, управление per chat.

**Инварианты:**
1. **Порядок роутеров `bot.py` НЕ меняется** (slava_presence → alan_greeting → kostik → alan → dead_page → war_alert → common → olya → slavik → vasya; новые — только добавками).
2. Гейтование — **на уровне фильтра**, не регистрации: роутер всегда зарегистрирован, но при выключенном модуле фильтр возвращает `False` (тихий игнор как для чужих сообщений).
3. **Никаких `hot.get` на import-time** — отложенный доступ при вызове фильтра (F-5-прецедент N3).
4. `kucha`, `vasya`, `dead_page`, `war_alert`, `direct_chat`, `search`, `youtube`, `web` — **вне плагина**, поведение без изменений.
5. SQLite-схема/инструменты истории — вне скоупа (RUNTIME WARNING).
6. Fail-open: недоступность PG/кэша → **безопасный дефолт** (читается как «выключено» — модуль не стреляет случайно; при повторной ошибке — лог, не спам).

---

## 2. Q1 — Фильтр-гейт: `PermsocGateFilter` (ключевой механизм)

`services/permsoc.py` (НОВЫЙ):

```python
class PermsocGateFilter(BaseFilter):
    def __init__(self, module_id: str): ...
    async def __call__(self, message) -> bool:
        chat_id = message.chat.id   # приватные чаты/каналы → False (кроме DM-веток алана, см. §4)
        return await permsoc_enabled(chat_id) and await module_enabled(chat_id, self.module_id)
```

- aiogram 3 поддерживает async-фильтры — ок; результат `True/False` (не UNHANDLED-паттерн).
- Внутренний user-match (**UserIdFilter остаётся внутри роутера-декоратора НЕЗАВИСИМО**): для slavik/kostik/alan — существующий `UserIdFilter(<id>)` остаётся вторым фильтром в декораторе (или эквивалентная проверка ID внутри), а `PermsocGateFilter` — первым (дешёвый гейт до match по ID).
- Порядок фильтров в декораторе: `[PermsocGateFilter, UserIdFilter|F-фильтр]` — не менять существующие вторые фильтры. Гейт НЕ зависит от user-match: мастер OFF → `False` даже когда ID совпал.

**Почему фильтр, а не регистрация-дифф:** роутеры объявляются на модуль (файл с `Router()`), их «динамическая регистрация» поломала бы grep-аудит, порядок включений, а главное — не позволила бы изоляцию per chat (регистрация — по процессу, гейт — по сообщению+чат).

---

## 3. Q2 — Master-тумблер + под-тумблеры

**Ключи:**
- **Master**: `flags.permsoc_enabled` — глобальный дефолт (REGISTRY, bool, **дефолт `false`** — `(изменено @Architect T-878)`: безопаснее для новых чатов; существующие чаты — бэкфил Q3).
- Per-chat master: `chat_params["gates"]["permsoc"]` (bool; namespace из F-7 §4.2). Приоритет: `gates.permsoc` (явный) → `overrides["flags.permsoc_enabled"]` (совместимость) → `hot.get("flags.permsoc_enabled", False)`.
- **Под-тумблеры** (существующие ключи, значения теперь через `hot_chat` — per-chat override поверх глобального дефолта):
  - `flags.olya_enabled` (Оля; дефолт False — как сейчас),
  - `flags.mimic_enabled` (передразнивания; дефолт False).
  - У Славика/Кости/Алана под-тумблеров НЕТ: модульная вкл/выкл = ТОЛЬКО master (+ их внутренние конфиги: `reactions.slavik_user_id`, `limits.kostik_reply_probability`, `reactions.alan_user_id` — работают как раньше). **Решение @Architect 08.09.2026 (девиансия M-F-9, вариант (a) — ПРИНЯТЬ):** `reactions.alan_mimic_enabled` — НЕ под-тумблер модуля alan, а легаси-выключатель common-мимикрии специально на Леху (архив-эпик 04.09.2026, §3.4.3: Лехе нужны ОБА флага — `flags.mimic_enabled` И `reactions.alan_mimic_enabled`; проверка остаётся в `handlers/common.py::mimic_handler`, в реестре PERMSOC_MODULES ему под-флаг НЕ назначен).
- Семантика: **master OFF → все 5 модулей игнор (полное молчание)**; master ON → модуль работает, если (для него нет собственного под-флага ИЛИ под-флаг даёт true); под-флаг OFF → точечное выключение только этого модуля.
- `module_enabled(chat, module)` реализация:

```python
async def module_enabled(chat_id, module_id) -> bool:
    sub = MODULE_SLOTS[module_id].sub_flag_key        # None | existing-kp
    if sub is None: return True
    return bool(await hot_chat.get(chat_id, sub, DEFAULT_SUB_FLAGS[sub]))
```

---

## 4. Q4 — Структура плагина `services/permsoc.py`

```python
@dataclass(frozen=True)
class PermsocModule:
    module_id: str            # 'slavik'|'kostik'|'alan'|'olya'|'mimic'
    title_ru: str             # 'Славик' ...
    target_user_id_key: str | None   # reactions.slavik_user_id и т.п. (или None)
    sub_flag_key: str | None  # flags.olya_enabled / flags.mimic_enabled / reactions.alan_mimic_enabled / None
    user_ids: tuple[int, ...]       # существующие hardcode-id (для аудита/телеметрии; при 0 -> офф)
    dependencies: tuple[str, ...]   # 'olya_relay','mimic_relay','mimic_transform' — только информ.
PERMSOC_MODULES: tuple[PermsocModule, ...]
```

Состав реестра (5 модулей):
| id | title_ru | target_user_id_key | user_id (хардкод) | под-флаг |
|---|---|---|---|---|
| slavik | «Славик (приветствия, kucha-реакции, GIF)» | `reactions.slavik_user_id` | 479167456 | — |
| kostik | «Костя (персона-реплики)» | `limits.kostik_reply_probability`-нет; поле ID — `reactions.kostik_user_id` **нет** → id 350803143 (хардкод остаётся; перенос в `bot_settings` — см. tma-ui-fixes T-876 «Telegram ID админа» — НЕ здесь) | 350803143 | — |
| alan | «Леха/Алан (имитация, приветствие)» | `reactions.alan_user_id` | 138811255 | — (решение 08.09.2026 M-F-9: под-флаг НЕ используется; «Мимикрия Лехи» = легаси-выключатель common-mimic в `handlers/common.py`, в модуль alan не входит) |
| olya | «Оля (видео-реакция)» | — | 834424825 | `flags.olya_enabled` |
| mimic | «Передразнивания (mimic)» | — | (по сообщению — не по участнику; база срабатывания `common.py` `_parse_mimic_victim_ids`, `limits.summary_aliases`) | `flags.mimic_enabled` |

**Сборка гейтов в хендлерах (не меняя bot.py):**
- `handlers/slavik.py` + `handlers/kostik.py`: декораторы `@slavik_router.message(PermsocGateFilter('slavik'), UserIdFilter(479167456), ...)` (реальная форма — как существуют; замена фильтра-деко или добавление первым параметром — по коду, с сохранением остальных F-фильтров).
- `handlers/alan.py` (главный триггер) + `handlers/alan_greeting.py` (greeting-ветка): декораторы с `PermsocGateFilter('alan')`; приветствие при мастер OFF — игнор (не «только при персональном сообщении» — гейт одинаковый; `is_private = chat.type in ('private','supergroup')` проверки остаются как в коде).
- `handlers/olya.py` + `handlers/filters/olya_video.py`: `PermsocGateFilter('olya')`; существующий `flags.olya_enabled` — теперь через hot_chat (не горячий import).
- `handlers/common.py::mimic_handler` + `services/mimic_relay.py` + `services/mimic_transform.py`: `PermsocGateFilter('mimic')` (гейт по чату-сообщению; фильтр — у самого `mimic_handler`), `flags.mimic_enabled` — hot_chat.
- **DM-пути для admin (`cmd_mimic_dm`, `cmd_alangreet_dm`)** — админские, НЕ гейтуются (управление ими остается в `admin_commands.py`).

---

## 5. Q3 — Включение по умолчанию + бэкфил

- **Новые чаты — OFF**: при `ensure_profile` (chat_lifecycle, T-777-прецедент) — пишем `chat_params["gates"]["permsoc"] = false` (если нет) в той же ветке, где F-10 пишет тяжёлые гейты; согласование: F-10 отвечает за тяжёлые, F-9 — только этот one gate (единый write-вызов: оба фичи через `set_chat_params` патч).
- **Существующие чаты — правило (детерминированное)**, `scripts/backfill_permsoc_gates.py` (НОВЫЙ; запуск @DevOps при деплое, до/вместе с restорта, идемпотентный, только stdout):
  ```
  master ON  ⟺ chat_id == -1002661910336
           OR chat_profiles.relations_enabled == true
           OR manual_lore <> '' OR auto_lore <> ''
           OR EXISTS (SELECT 1 FROM chat_admins WHERE chat_id = ...)
  master OFF — иначе
  ```
  Повторный запуск — no-op (гейт уже записан, **не перезаписываем** существующее значение); значения пишутся только если `gates.permsoc` отсутствует.
- Глобальных чатов «живых» сейчас: только ярый + кастомизированные — по правилу они остаются ON (ровно текущее поведение), все новые/чужие — OFF.

---

## 6. Q5 — TMA-секция + Q6-инвентарь

- **Секция «Функции PERMsoc»**: временно — карточка во вкладке «Реакции и Триггеры» (F-11 перенесёт в «Модули и Фичи»): master-тумблер (write — ТОЛЬКО глобальный admin через gates-API F-10 `PUT /api/chat/{chat_id}/gates {feature:'permsoc'}`) + 5 под-тумблеров (олya/mimic — реальные; slavik/kostik/alan — derived от master, disabled-вид; под-тумблер alan НЕ выводится (у модуля под-флага нет — решение 08.09.2026, §9)) — для глобального админа тумблеры редактируемые; **local admin — только чтение** (статус-бейджи; изменять не может, по решению F-10 who_can_toggle: permsoc — global-only).
- Данные под-тумблеров: olyа/mimic/alan — из `GET /api/config` (X-Chat-Id, значения `flags.olya_enabled`/`flags.mimic_enabled`); для alan под-флаг НЕ читается (статус-бейдж `derived (master)` — как slavik/kostik), а legacy-выключатель «Мимикрия Лехи» (`reactions.alan_mimic_enabled`) остаётся в существующем месте (KV-редактор, группа reactions_mimic), master — из `GET /api/chat/{id}/gates`.
- **Телеметрия**: счётчики включённых чатов (master ON) в `services/status_service.py` / `GET /api/status` (N из M) — без ключей; переключения — история `chat_lore_history field='gates'` + лог `[permsoc] gate changed | chat=%s | by=%s` (без значений).

**Q6 инвентарь (точки кода, затрагиваемые фичей):**
- `handlers/slavik.py` (:16 Router, :117 setup), `handlers/kostik.py` (:23 Router), `handlers/alan.py` (:24 Router, :112 setup), `handlers/alan_greeting.py` (:24 Router), `handlers/olya.py` (:18 setup), `handlers/filters/olya_video.py` (фильтр), `services/olya_relay.py`, `services/mimic_relay.py`, `services/mimic_transform.py`, `handlers/common.py` (:51 setup_common_mimic, :228 mimic_handler).
- `services/param_catalog.py`: REGISTRY-записи `flags.permsoc_enabled` (НОВАЯ), `flags.olya_enabled`, `flags.mimic_enabled`, `reactions.alan_mimic_enabled`, `reactions.slavik_user_id` — существующие (группы flags/reactions; для новых — категория flags, группа `flags_media` или новая `flags_permsoc`, порядок).
- TMA: `web/app.js` (вкладка reactions_triggers — карточка), `web/index.html`.
- Тесты: `tests/test_permsoc.py` (НОВЫЙ), существующие `test_direct_chat`/`test_olya`/`test_slavik`/`test_alan*` — моки аioфреймворка с новыми фильтрами.
- **НЕ трогаем**: kucha-реакции (`handlers/slavik.py` внутри), `vasya`, `dead_page*`, `war_alert`, `admin_commands` (кроме 5 гейтов), `bot.py` — ТОЛЬКО если уже есть setup-добавки (permsoc не требует DI: фильтры самодостаточны; setup_permsoc не нужен в bot.py при фильтрах-декораторах).

---

## 7. Тест-инварианты (E1/E2)

1. `permsoc_enabled`/`module_enabled` matrix: master OFF → все 5 False; master ON + суб-флаг OFF → модуль False; master ON + суб ON → True (для модулей без суб — True: slavik/kostik/alan, решение 08.09.2026); per-chat различие (чат A True, чат B False — через chat_params-мок).
2. `PermsocGateFilter` — единичный вызов не роняет: чат не активен/нет chat_id → False; async-фильтр тестирования в mocked aiogram (FakeMessage).
3. Lifecycle: новый чат → `gates.permsoc=false`; повторный вход → не перезаписывает.
4. Бэкфил-скрипт: идемпотентен (двойной запуск no-op), не затирает существующие `gates`-значения.
5. Регресс путей включённых модулей — старые тесты с новым фильтром: срабатывают при master ON, не матчат чужого юзера, relay-сервисы вызываются только при ON (маркеры вызовов).
6. Grep-аудит: порядок include_router в bot.py не изменён; import-time hot.get в новых файлах отсутствует (флаг-аудит).
7. Полный pytest → 0 failed; `git diff --check`.

## 8. Риски для @Builder

1. **Async-фильтры + aiogram-моки**: если существующие тесты синхронно вызывают фильтры — обёртка; при сомнении реализовать `async def __await__`-паттерн не надо — aiogram 3 допускает async фильтры, тесты обновлять.
2. **`setup_slavik(db)`-DI**: внутри slavik live-кэш ходов — не менять; гейт — только decorator-слой.
3. **Реальные user_id в коде хардкод**: Т866/T876 вынос «Telegram ID» в TMA не трогает работу; фильтр читает target user id и из конфига, и из хардкода (минимум: хардкод остаётся, конфиг-переопределение — динамическое).
4. **Гонка T-884/C1 с F-10**: оба пишут в `chat_params.gates` при ensure_profile — единый патч-метод F-7 `set_chat_params`; в C1 только `permsoc`, в T-895/F-10 — тяжёлые; НЕ делать два отдельных UPDATE.

---

## 9. Запись решения по девиансии M-F-9 (08.09.2026, @Architect)

**Выбран вариант (a) — ПРИНЯТЬ отклонение @Builder:** модуль alan гейтуется ТОЛЬКО master-тумблером (`sub_flag_key=None`), а `reactions.alan_mimic_enabled` остаётся легаси-выключателем common-мимикрии на Леху и в модульный гейт НЕ входит. **§3 (под-тумблеры), §4 (таблица-реестр), §6 (TMA-секция), §7 (тест-инвариант 1) обновлены в соответствии с этим решением.**

**Обоснование (кратко):** (1) прод-сид `reactions.alan_mimic_enabled = False` → цепочка `master AND sub` выключила бы живые приветствия/реплики Лехи в `-1002661910336` сразу после бэкфила (master ON) — регресс живого поведения без спасения кем-либо; (2) этот ключ имеет устоявшуюся семантику «Мимикрия Лехи» (Лехе нужны ОБА флага: `flags.mimic_enabled` И `reactions.alan_mimic_enabled`; других жертв не касается — архив-эпик 04.09.2026 §3.4.3) — навешивать на него модульный гейт алана = смешение двух разных фич и сбитая карточка; (3) alan структурно в одном классе со slavik/kostik (персона: реплики + приветствие) — у тех под-флагов тоже нет, реестр консистентен; (4) вариант (b) потребовал бы бэкфил-записи под-флага прод-чату и каждому новому чату + дуальный смысл ключа в UI — сложнее при том же результате (master решает всё).

**Проверка инвариантов после решения:**
- Оригинальный чат `-1002661910336` (мастер ON после бэкфила): Леха имитация/приветствие — работает (мастер ON ∧ под-флага нет ⇒ True). New chats: мастер OFF ⇒ все 5 (включая alan) молчат.
- Common-mimic на Леху: гейт прежней цепочки (мастер ON + `flags.mimic_enabled` + `reactions.alan_mimic_enabled` через hot_chat в `mimic_handler`) — без изменений.
- TMA-тумблер не инертен: интерактивный под-тумблер для alan НЕ выводится вовсе, вместо него — статус-бейдж `derived (master)` (read-only, как у slavik/kostik), а «Мимикрия Лехи» остаётся в своём существующем месте (KV-редактор, группа reactions_mimic). Инертного переключателя не существует: ни один несрабатывающий контрол не выведен.

**Следствия для @Builder (небольшие доработки — подтверждающие):**
1. `services/permsoc.py` — **логика без изменений** (alan: `sub_flag_key=None`, как есть): удалить мёртвый ключ `"reactions.alan_mimic_enabled"` из `DEFAULT_SUB_FLAGS` (ни один модуль его не использует) и убрать его из docstring-перечня под-флагов (строки 14-16); комментарий P1-правки (59-63) — оставить.
2. `scripts/backfill_permsoc_gates.py` — **без изменений** (пишет только `gates.permsoc`; sub-флаг для alan не нужен: новые чаты глушит мастер OFF).
3. TMA (`web/index.html` ~строки 814-818): бейдж строки `alan` — `derived (master)` (как slavik/kostik), НЕ «под-флаг».
4. Тесты `tests/test_permsoc.py`: кейс alan = мастер ON + нет sub-флага → `module_enabled == True` (добавить в матрицу §7 п.1).
