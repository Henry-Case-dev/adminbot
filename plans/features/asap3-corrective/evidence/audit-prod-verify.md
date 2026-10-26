# AUD-PROD-VERIFY — консолидированный аудит трёх дефектов (факт-матрица)

Лейн: `RESIDUALS-ASAP23` (task/res23). Дата составления: 27.10.2026.
**Нового доступа к прод/SSH/Telegram не было.** Документ сводит уже принятые
read-only факты (аудиты 2026-10-23: release-258113/258114/258118; релизные
отчёты 2.58.130) в одну матрицу «дефект × атрибут» по требованию строки
`AUD-PROD-VERIFY` карты asap3: фактический код, активные значения PostgreSQL,
заводские значения, реальный путь применения — для каждого из трёх дефектов.

Дефекты (root causes из `final-report.md` §1):
- **P1** — скрытая обрезка style-hint 400/5 (`lines.pop()`, `[:400]`);
- **P2** — скрытый override/имена: менее приоритетные источники перебивали
  действующий алиас (`get_chat_param`/порядок резолва);
- **P3** — скрытые лимиты (молчаливые потолки, DI-подмена, невидимые потери).

---

## 1. P1 — обрезка style-hint 400/5

| Атрибут | Факт | Источник |
|---|---|---|
| Фактический код (было) | `prompt_style_blocks.py:431-432,466-469`: `0` = «применить 400/5»; `:494-515`: `lines.pop()` срезал последние инструкции владельца; единственная строка >400 → `""` при живых правилах | `evidence/style-phase1.md` §1.1–1.2 |
| Фактический код (стало) | `HINT_LIMIT_OFF = 0` (`prompt_style_blocks.py:438`); `HintRender` (`:479-688`): атомарные инструкции, `excluded[{key,kind,reason}]`, `truncated=false`; второй сборщик в композере удалён (`prompt_composer.py:840-853`, снимок только через `style_policy.resolve_style_policy_ref`) | `evidence/style-phase1.md` §1.1–1.3 |
| Активные значения PG | Прод, read-only `SELECT style.policy` (rev 12): `hint_limits` **отсутствует** (`STYLE_HINT_LIMITS_PRESENT=False`) → скрытой обрезки нет; `rules` владельца: `emoji.hard.off`, `quotation_marks.hard.no_graphic`, `trailing_period.hard.strip` (`enabled=True`) | `_audit-2026-10-23/release-258114/deploy.md` §строка 10 |
| Заводские значения | Заводских 400/5 больше нет: отсутствие/`0` = без ограничения; заводское правило тире синтезируется кодом `dash.hard.factory` (`enabled=True`, hard, global) — `style_policy.py:947-970,1019`; на проде «dash активен» | `evidence/style-phase1.md` §1.1, §2; `release-258114/deploy.md` §10 |
| Реальный путь применения | Резолв: `effective_style_policy(chat_id)` (`style_policy.py:1173`) → `effective_policy_sync` (`:1060`, source=default/global/chat) → снимок `resolve_style_policy_ref` в композер (слой 10, `versions.style_policy`) → egress `verify_outbound_payload` (S6); `compile_style_prompt` импортируется на проде (проверка деплоя 2.58.130) | `evidence/style-phase1.md` §1.3; `plans/features/cfg/evidence/release-258130.md` §Deploy; `evidence/acceptance.md` S6 |

## 2. P2 — скрытый override/имена (идентичность)

| Атрибут | Факт | Источник |
|---|---|---|
| Фактический код | Единый резолв по `user_id`: `AliasResolver`, `LiveAliasView` + `bind_turn_aliases(chat_id)` (ContextVar), middleware `dp.update`; chat_params — единый слой override с явным скоупом; ручного списка запрещённых старых имён нет | `final-report.md` §2, §4; `evidence/identity-phase.md`; `review-identity-r2.md` (APPROVED) |
| Активные значения PG | Прод, read-only `manage.py diag aliases --chat-id -1002661910336 --show-names`: **39 пользователей**, merged-цепочка; чатовый override отличается от глобального только у `uid=529151103` (`chat=Папаха / global=Толян → effective=Папаха`) — эффективное значение chat>global подтверждено на живых данных; алиасы 39 пользователей сохранены миграцией без перезаписи | `_audit-2026-10-23/release-258114/deploy.md` §11, §8 («кастом юзера — НЕ трогаем») |
| Заводские значения | Заводского ручного списка имён нет: grep диффа — 0 литеральных имён/ID; при отсутствии override — наследование global → Telegram nickname/username → память (порядок фиксирован) | `final-report.md` §4 (REPORT-ALIAS-RULES); binding-final §2 |
| Реальный путь применения | Update → сохранённый автор (uid) → резолв алиаса по uid → контекст LLM → генерация → исходящее (тот же порядок, что прод-маршрут); без рестарта: `test_a4/a5/a6` — глобальная/чатовая правка применяется со следующего хода и переживает рестарт | `final-report.md` §5 (REPORT-LIVE-APPLY-PROOF); `evidence/acceptance.md` A4–A6 |

## 3. P3 — скрытые лимиты

| Атрибут | Факт | Источник |
|---|---|---|
| Фактический код | Инвентаризация 23 ограничений: 5 USER_VISIBLE, 8 TECHNICAL_VISIBLE, 4 HIDDEN_LOSS (исправлены), 6 NOT_RELEVANT; молчаливый потолок привычек `SOFT_INSTRUCTIONS_MAX=12` → 64 (`style_policy.py:69`, `:756-761`), `soft_truncated`/`rules_truncated` — fatal-диагностика | `evidence/limits-inventory.md` §1–2; `evidence/style-phase1.md` §1.4 |
| Активные значения PG | Прод rev 12: `hint_limits` отсутствует → ни одного скрытого лимита hint; бюджетные исключения видны отдельно (`budget_excluded` ≠ user_limit) | `_audit-2026-10-23/release-258114/deploy.md` §10; `evidence/acceptance.md` S10 |
| Заводские значения | Дефолт лимитов владельца = OFF (0 = без ограничения); заводские правила — только `dash.hard.factory` (синтез, см. P1); остальные каталог-дефолты — зеркала рантайм-резолверов (`config_cache.py:58-80`) | `evidence/style-phase1.md` §2; `services/config_cache.py` |
| Реальный путь применения | Лимиты применяются только там, где владелец их задал: S4 — реальный save-путь `chat_params.set_chat_params` → инвалидация → `effective_style_policy` без рестарта; S5 — изоляция чатов; Inspector показывает фактическую сборку (S9); техбюджет не маскируется под лимит владельца (S10) | `evidence/acceptance.md` §3 S4/S5/S9/S10; `tests/test_asap3_acceptance.py` |

---

## 4. Границы и свежесть

- Все прод-факты — из read-only аудитов 23.10.2026 (release-258114 deploy,
  один логин `nik`, интервалы ≥60 с) и деплой-отчёта 2.58.130 (24.10);
  сессия RESIDUALS-ASAP23 прод не трогала.
- Локальное переподтверждение кодовой части в этом worktree (база
  `d3a9a2cc`, 27.10.2026): `tests/test_asap3_acceptance.py` +
  `tests/test_asap3_style_hint_limits.py` → 24 passed; `compileall services` → rc=0.
- Тесты ON-vs-legacy паритета `tests/test_soul1_composer_parity_off.py`
  (4 шт.) падают на этой базе предсуществующе: ON-путь добавляет слой
  `<Speech_Base>` (p0-int R2). К записанным дампам P1–P5 отношения не имеет
  (`-k matches_recorded_dump` → 4 passed). Классификация: смежное
  предсуществующее наблюдение, вне скоупа asap3.
