# CFG-02A — суточная квота изображений: видима, управляема, реально влияет

Слайс: **CFG-02A** (карта `plans/features/cfg/requirements-map.json`: строки `CFG-02.D`,
`CFG-02A.1–02A.7`, `CFG-02.AC1`). Лейн: CFG-02A (writer).
Источник: `plans/features/cfg/source-cfg-addendum.md`, раздел CFG-02A (L69–L77).
Кандидат: коммит `feat(cfg): CFG-02A — daily image quota: visible, manageable, effective`
(18 файлов) на базе `2bc13f44c548`; контент-стабильные blob sha12 — §7 / `red-green.txt`. Sha
самого коммита фиксируется в отчёте Builder при handoff (любая правка evidence меняет его).

## 1. Корневая причина UI-дефекта (воспроизведена на базовом коде)

`limits.image_daily_limit` существовал в каталоге (`services/param_catalog.py`), но в
MiniApp **не рендерился нигде**:

* `web/app.js` — витрина вкладки `mod_images` объявляла только
  `sources: [{category:'flags', groups:['flags_module_images']}]`; группа `limits_images`
  (из Python-`TAB_RULES` `TAB_MOD_IMAGES`) в зеркале **отсутствовала** → `groupedForTab`
  не отдавал группу вообще;
* как следствие, `workspaceTabHasContent('limits')` = false → вкладка «Лимиты» скрывалась
  как пустая, а висевшая на ней read-only врезка (`data-image-limits`) была недостижима;
* требуемое владельцем место — **«Основные настройки»** модуля (L71), т.е. даже при
  наличии вкладки «Лимиты» требование не выполнялось бы.

Итог: у владельца не было ни видимого значения, ни управления; наличие ключа в
`param_catalog.py` доказательством не являлось (прямая формулировка L65).

## 2. Что сделано (минимальная реализация в существующих механизмах)

| Файл | Дельта |
|---|---|
| `web/app.js` | (1) зеркало `TAB_RULES`: `mod_images.sources += {category:'limits', groups:['limits_images']}` (корневая причина); (2) `workspaceGroupTab`: `limits_images` → `'settings'` («Основные настройки», требование L71); (3) витринные подписи `CONFIG_GROUP_DISPLAY['limits_images']` = «Лимиты генерации» и `CONFIG_ITEM_DISPLAY_OVERRIDES['limits.image_daily_limit']` = «Изображений в сутки» + единицы/семантика/политика списания (Δ каталога = 0, прецедент B07); (4) `imageQuotaFacts` (computed): фактическое значение области + источник из **существующих** поверхностей (`configItems` + `GET /api/workers/budget`); (5) `saveImageDailyLimit` — единственный write-path (`saveConfigItem` → `POST /api/config`), клиентский запрет невалидного ввода и no-op guard (0 POST, когда значение не менялось); (6) `maybeLoadImageQuota` — ленивый догруз фактов на вкладке «Основные настройки» (прецедент `maybeLoadVisionState`, окно 30 с); (7) `imageResetLabel(iso, tz)` — время сброса показывается в TZ ДНЯ КВОТЫ (не в TZ браузера). |
| `web/index.html` | Секция «Лимиты генерации» в карточке группы `limits_images` (на «Основных настройках»): поле `limits.image_daily_limit` (`type=number min=-1 step=1`) + факты (`data-image-quota-*`): фактическое значение, источник (чат/глобально/заводской), расход, остаток, TZ, ближайший сброс, общий env-бюджет, честный режим применения и подсказка про списание. Старая врезка `data-image-limits` (отдельная вкладка) **удалена** — одно место фактов, одно место настройки (второго источника истины нет). |
| `services/worker_budget.py` | `image_usage_summary` += аддитивные честные поля `reserve_path`/`reserve_reason` (из `image_generation.image_reserve_mode`). Плюс исправлен найденный дефект учёта: при `−1` (безлимит) per-chat счётчик в reserve-пути **не инкрементировался** (shared-контур инкрементировал) → UI показывал бы «расход 0»; теперь UPSERT без cap (паритет shared и legacy `consume`). |
| `services/image_generation.py` | `image_reserve_mode(chat_id)` — единый источник гейтов reserve/legacy (используется и `_reserve_or_consume`, и диагностикой); `image_quota_reset_note(chat_id)` — честное фактическое время сброса (календарный день чата в его TZ); строка добавляется к отказу по суточной квоте в direct-пути. |
| `services/tool_router.py` | Семантический путь (`generate_image`): к отказу по квоте добавляется та же фактическая строка времени сброса (единый helper). |
| `tests/test_cfg02a_image_quota_ui.py` (новый) | 27 тестов: контракт каталога/витрины, факты UI, GLOBAL/CHAT/сброс/0/−1/1/второй чат/рестарт/смена суток+TZ/параллель/shared-limit/factory, отказ до платного вызова + честный сброс, пользовательские пути и повтор, ошибка провайдера и доставки. |
| `tests/test_soul1_capability_fallbacks.py` | Точечное обновление одного кейса: для `quota_exhausted` сообщение инструмента = управляемая форма реестра **+** фактическая строка сброса (ассерты строже: префикс + наличие факта); остальные коды не изменены. |
| `tests/js/round1024_image_module_test.js` | F5-пин состава вкладки `mod_images` обновлён под CFG-02A (одна owning-задача): теперь ожидается `['flags_module_images','limits_images']` **плюс новые негативы** — `limits_images` не дублируется ни в одной другой вкладке (один дом). Ассерты не ослаблены. |
| `tools/ui_cfg02a_image_quota_e2e.py` (новый) | Playwright-e2e (стабы `/api/*`) + режим `--serve` для визуальной проверки Browser Use. |

Переиспользованы: каталог-группа и ключ (один источник истины), `ConfigCache`/hot-reload,
`ChatParamsCache` (per-chat overrides + TTL/NOTIFY), `worker_budget.reserve_image`
(атомарный резерв/журнал/commit-release), `capability_registry` (речевые формы),
`GET /api/workers/budget` (факты §27), витринные `CONFIG_GROUP_DISPLAY`/
`CONFIG_ITEM_DISPLAY_OVERRIDES`. **Второй счётчик, второй резолвер и второй параметр не
созданы.**

### Семантика значения (проверена по фактической реализации)

`0` = генерация запрещена (отказ до платного вызова, без расхода); `−1` = безлимит (расход
учитывается); `>0` = сколько генераций в сутки разрешено чату. День квоты — календарный день
чата в его TZ (`limits.chat_timezone` → `CHAT_TIMEZONE` → `SUMMARY_TIMEZONE` → UTC), сброс —
полуночь (не «24 часа от первого запроса» и не короткий cooldown). GLOBAL — дефолт для
чатов, CHAT override независим, сброс override возвращает наследование и **не** меняет
GLOBAL. Единица списания — генерация (одна картинка за запрос; повторная обработка того же
запроса и повторная доставка квоту не списывают — idempotency журнала).

## 3. Покрытие строк карты (статус-план)

| Строка | Статус-план | Доказательство |
|---|---|---|
| CFG-02.D (UI-дефект) | `TESTED` | RED на базе `2bc13f44` (те же тесты: 10 failed) → GREEN на кандидате (27 passed); RED-причины: отсутствие витринных подписей, `limits_images` в зеркале/маппинге вкладки, фактов квоты, честного режима и времени сброса. E2E: секция видна на «Основных настройках», поле редактируется, невалидный ввод не уходит (`ux-e2e` §4). |
| CFG-02A.1 | `TESTED` + `READY_FOR_LIVE` (preprod) | `test_vitrina_labels_and_units` (витринные подписи), `test_js_mirror_declares_limits_group`, `test_limits_group_renders_on_settings_tab`, `test_group_belongs_to_images_module_tab`, e2e `settings_section_visible`/`section_title`; живая проверка §5.1. |
| CFG-02A.2 | `TESTED` + `READY_FOR_LIVE` (preprod) | `test_ui_marks_facts_and_guard`, `test_ui_hint_is_factual`, e2e `facts_*` (значение/единицы/источник/расход/остаток/TZ/сброс/подсказка), скриншоты `ui/browseruse-390-settings-section.png`, `ui/01-settings-global.png`; живая проверка §5.1. |
| CFG-02A.3 | `TESTED` + `READY_FOR_LIVE` (preprod) | `test_global_change_takes_effect_without_restart`, `test_small_positive_one_then_deny`, `test_zero_is_forbidden_and_does_not_consume`, `test_minus_one_is_unlimited_and_still_accounted`, `test_chat_override_isolated_and_reset_keeps_global`, `test_factory_default_when_keys_absent`, `test_invalid_type_in_override_falls_back_to_global`, `test_client_guard_blocks_invalid_value` (клиентский запрет + no-op guard), e2e `invalid_posts_count=0`, `chat_scope_*`; живая проверка §5.1/5.2. |
| CFG-02A.4 | `TESTED` + `READY_FOR_LIVE` (preprod) | `test_global_change_takes_effect_without_restart` (10→2→5 без рестарта, третий отказ), `test_reserve_mode_is_honest` (reserve/legacy+budgets_off/kill_switch_off), `test_shared_env_limit_denies_even_with_chat_quota_left`, e2e `legacy_mode_notice`, `budgets_off_notice`, `facts_mode`; живая проверка §5.3. |
| CFG-02A.5 | `TESTED` + `READY_FOR_LIVE` (preprod) | `test_deny_before_paid_call_with_reset_time` (0 генераций, журнал `denied/limit_chat`), `test_refusal_text_carries_honest_reset_time` (форма SOUL-1 + «Суточная квота обновится 19.10.2026 00:00 (TZ)», без cooldown-лексики), `test_reset_note_is_fail_open`; живая проверка §5.4. |
| CFG-02A.6 | `TESTED` (пользовательские пути) + **открытая часть: изоляция обложек — CFG-02C** | `test_direct_and_tool_paths_use_chat_quota` (direct/tool — реальный `chat_id`, повтор → `already`, без второго списания), `test_provider_error_returns_quota_and_delivery_keeps_charge`. Замер состояния обложек — §6 (R2): hard-split accounting (`user_image`/`summary_cover`) — owning-задача **CFG-02C** (ADD-1.T2/L93–L105), в этом слайсе не дублируется. |
| CFG-02A.7 | `TESTED` (песочница, без платных прод-прогонов) | Тесты §2 (GLOBAL/CHAT/возврат/0/−1/1/второй чат/рестарт/смена суток+TZ/параллель/provider/Telegram delivery/shared/factory) — 27 тестов файла; PG-стаб in-memory (без внешних расходов). |
| CFG-02.AC1 | `READY_FOR_LIVE` (preprod) | Локально: `test_global_change_takes_effect_without_restart`, e2e (видимость/правка/сохранение/переживание reload — `facts_value_after_save`); mobile 390 — `mobile_section_visible`, `mobile_no_overflow`; живая проверка §5.1/5.5. |

Живые строки (02A.1/02A.2/02A.3/02A.4/02A.5/AC1) локально закрыты поведенчески и E2E, но
**не** `VERIFIED`: их подтверждает живой сценарий §5 на preprod (ADD-0.1; plan §процесс.4).

## 4. Прогоны (команды и результаты)

```text
# RED (worktree базового коммита 2bc13f44, те же новые тесты)
py -3 -m pytest tests/test_cfg02a_image_quota_ui.py -q
  → 10 failed, 17 passed  (пре-существующее поведение зелёное; красное — новое)
py -3 -m pytest tests/test_soul1_capability_fallbacks.py -q      # обновлённый кейс
  → 1 failed, 40 passed  (base не содержит фактической строки сброса)

# GREEN (кандидат)
py -3 -m pytest tests/test_cfg02a_image_quota_ui.py -q
  → 27 passed
py -3 -m pytest <26 файлов: image/param/webapp/frontend/soul1/summary/budget/tool_router/
                  hotfix5/unified/mca/matrix/settings-persistence> -q
  → 608 passed
py -3 -m pytest tests/test_soul1_capability_fallbacks.py tests/test_round1025_f8_registry.py \
                tests/test_param_catalog.py tests/test_frontend_tab_mapping.py -q
  → 207 passed (замороженные срезы каталога/роутов НЕ сдвинуты: Δ каталога = 0)

# UI E2E (детерминированный, стабы API; без внешней сети)
.venv\Scripts\python.exe tools\ui_cfg02a_image_quota_e2e.py
  → RESULT: PASS (console_errors = 0; 5 скриншотов в ui/)
```

Новые тесты помечены `TEST-LIFECYCLE: CONTRACT/REGRESSION owner=CFG-02A`.

## 5. Живые проверки (preprod; выполняет DevOps/Orchestrator после деплоя)

1. **Видимость и фактическое значение (02A.1/02A.2/AC1)**: MiniApp → «Модули» → «Генерация
   изображений» → «Основные настройки»: секция «Лимиты генерации», «Изображений в сутки»,
   единицы «генераций/сутки», источник (чат/глобально/заводской), расход, остаток, TZ,
   ближайший сброс. Проверить на мобильном и десктопе.
2. **Управляемость и влияние без рестарта (02A.3/02A.4)**: GLOBAL 60 → 2 → две генерации
   проходят, третья — отказ с фактическим временем сброса; вернуть 60 → генерация снова
   проходит. Затем выбрать чат, задать 1 → второй чат продолжает по GLOBAL; «↪ Глобальное»
   возвращает наследование, GLOBAL не меняется.
3. **Честность режима (02A.4)**: при `IMAGE_DAILY_LIMIT_ENABLED=OFF` (env) секция показывает
   warning про legacy-счётчик; при master `flags.budgets_enabled=OFF` — «лимит НЕ
   ограничивает генерацию»; при доступном shared-лимите виден «Общий технический бюджет всех
   чатов (env-only)».
4. **Отказ (02A.5)**: речевая форма SOUL-1 + фактическое время сброса по TZ; в логах отказа
   нет платного вызова провайдера (по usage/логам).
5. **Сохранность (AC1)**: после перезагрузки MiniApp и рестарта сервиса значение сохраняется,
   счётчик дня не обнуляется.

## 6. Девиации, риски, побочные находки

* **R1 (каталог vs витрина).** Названия/единицы/семантика сделаны витринным слоем
  (`CONFIG_GROUP_DISPLAY`/`CONFIG_ITEM_DISPLAY_OVERRIDES`), а не правкой `services/param_catalog.py`:
  каталог заморожен инвариантами `test_round1025_f8_registry.py` (sha256 + генератор
  документации), а витринный слой — прецедент B07 («Δ каталога = 0»). Каталоговое
  переименование и каталоговые границы min/max для ВСЕХ параметров — owning-задача **CFG-03**
  (аудит всех параметров; прецедент R1 CFG-01). Поведение рантайма при этом честное.
* **R2 (изоляция обложек Summary, часть 02A.6).** Замер на базовом коде: `summary_generator`
  вызывает `generate_image_verbose(..., chat_id=<чат>)` — обложка Base расходует ТОТ ЖЕ
  per-chat счётчик `image_calls`, что и пользовательская квота (а при `0` — блокируется им);
  `cover_style_preview` вызывает тот же генератор с `chat_id=None` (per-chat счётчик не
  трогает). Жёсткое разделение accounting (`user_image`/`summary_cover`, отрицательные тесты)
  — owning-задача **CFG-02C** (ADD-1.T2, L93–L105); в CFG-02A не дублируется (ADD-0.2), в
  UI этого слайса ложных утверждений про обложки нет. **Важно для CFG-02C:** текущее
  поведение нарушает L76/L105 и должно быть закрыто именно там.
* **R3 (исправленный побочный дефект учёта).** В reserve-пути при безлимите (`<0`) per-chat
  счётчик не инкрементировался (в отличие от shared-контура и legacy `consume`) → UI
  показывал бы «расход 0» при реальных генерациях. Исправлено в `worker_budget.reserve_image`
  (UPSERT без cap) и закреплено тестом `test_minus_one_is_unlimited_and_still_accounted`.
* **R4 (обновление одного SOUL-1 кейса).** `test_tool_path_message_uses_template_by_code`
  для `quota_exhausted` теперь проверяет «управляемая форма-префикс + фактическая строка
  сброса» (ассерты строже, остальные коды без изменений) — требование 02A.5 + L75.
* **R5 (клиентские границы).** UI не отправляет не-целые и значения < −1 и не сохраняет
  no-op (0 POST). Серверный слой по-прежнему проверяет только тип (`int` → 422 для
  не-int); диапазонные серверные границы каталога — CFG-03 (см. R1). Любое отрицательное
  значение рантайм трактует как безлимит (существующая семантика `budget_limits`), UI
  предлагает документированное `−1`.
* **R6 (обновление F5-пина состава вкладки).** JS-юнит `tests/js/round1024_image_module_test.js`
  фиксировал состав `mod_images` как ровно `['flags_module_images']`; CFG-02A расширяет его на
  `limits_images` (требование 02A.1 — настройка обязана рендериться в модуле). Пин обновлён
  осознанно (одна owning-задача) и **усилен**: добавлены негативы «нет дублей в других
  вкладках». Это единственный красный полного прогона, вызванный слайсом (остальные 12 —
  предсуществующие, воспроизведены на базе).
* **Побочная находка (не дефект прода):** в UI-харнессе бейдж «скрыт» появлялся из-за
  стабов (`view_roles: []` вместо реальной матрицы ролей) — стаб исправлен
  (`access.default_matrix`), скриншоты без ложного бейджа.
* **Побочная находка (инфраструктура):** `browser_harness`-скриншоты периодически падают по
  таймауту `Page.captureScreenshot`; визуальная проверка выполнена (кадры §2 + DOM-факты),
  2 удачных кадра сохранены. На продукт не влияет.

## 7. Runtime entrypoints, тесты и fingerprint (для манифеста)

* entrypoints: `web/app.js::workspaceGroupTab` (маппинг `limits_images` → settings),
  `web/app.js::imageQuotaFacts`/`saveImageDailyLimit`/`maybeLoadImageQuota`,
  `web/index.html` (секция `data-image-quota-facts`), `services/worker_budget.py::reserve_image`
  (учёт при безлимите), `worker_budget::image_usage_summary` (additive `reserve_path`),
  `services/image_generation.py::image_reserve_mode`/`image_quota_reset_note`/`_image_error_block`,
  `services/tool_router.py::ToolRouter._generate_image`.
* тесты: `tests/test_cfg02a_image_quota_ui.py` (новый, 27),
  `tests/test_soul1_capability_fallbacks.py` (1 кейс строже), e2e
  `tools/ui_cfg02a_image_quota_e2e.py`.
* fingerprint: 18 файлов кандидата, база `2bc13f44c548`; blob sha12 ключевых файлов — см.
  `red-green.txt` §CANDIDATE (контент-стабильно; sha коммита — в отчёте Builder).
