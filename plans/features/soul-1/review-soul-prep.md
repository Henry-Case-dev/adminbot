# SOUL-PREP — проверка подготовки релиза SOUL-1 — РЕВИЗИЯ R3 (18.10.2026)

**Вердикт R3: Approved** (для `soul-release-prep.md` @ `e424f0b8`). Релизный гейт при этом **не закрыт**: payload-precondition остаётся открытым (см. «Открытые условия включения»).

## Привязка

| Поле | Значение |
|---|---|
| Артефакт | `plans/features/soul-1/soul-release-prep.md` — коммит `e424f0b8` (только этот файл, +15/−7, родитель `282978cd`) |
| История ревизий | R1: F1/F2/F3 → R2: F4/F5 → R3: проверка правок R2 (этот документ) |
| Кандидат | runtime == `6094a2cf`; `git diff 6094a2cf HEAD -- services web` = пусто (мой прогон R2) |
| Evidence payload-лейна | `plans/features/soul-1/evidence/soul-release/payload-verification.md` (194 строки) + каталог `payload-verification/` (`stand.py`, `stand-output.txt/json`, `stand-run.log`, `focused-tests.txt` = 96 passed) — закоммичены вместе с этим вердиктом |
| Секрет-скан артефактов | 6/6 чисто (api-key/token/Bearer/DSN/пароли — 0 совпадений) |

## Результаты проверки R3 (по пунктам)

1. **F4a — закрыт.** §0-шапка, §2 и §5 ссылаются на каталог `evidence/soul-release/payload-verification/` и на итоговый `payload-verification.md`; мёртвых ссылок нет, оба объекта существуют (md — 194 строки, реальный отчёт с findings и границами).
2. **F4b — закрыт.** Критерии (i)(ii)(iii) в §5 сформулированы корректно, источники названы («PG, Python, фабрика, fallback»): (i) 11 withheld + `source=default` + отсутствие legacy в effective 5 путей (совпало с моим прогоном R2 и со стендом: factcheck `2f61c20e3eaa`, search `b74c40b30ec1`, checkup `b5295b0c250a`, direct `45b531879b50`, narrator `95141f190d8b`); (ii) `summary_editor` + per-chat `summary_cover_style` — контент захвачен и вердикт дан (в отчёте честно «content not captured» → критерий открыт); (iii) 4 Python-блока (`message.smartmodule.chat_persona`, `style.bot_knowledge`, `internal.lore.story`, `internal.nostalgia.candidate`) — достижимость в 5 путях (Direct/Initiative/Factcheck/Summary/fallback) разрешена до включения осей. Идентификаторы блоков сверены со свипом стенда.
3. **F4c — закрыт.** Verify-шаг 3 прямо фиксирует, что `_gate_state()` (10 ключей) не покрывает `HUMOR_CRAFT_ENABLED` и ось инициативы, и требует отдельной проверки env процесса + фактического PG-ключа, а для инициативы — `POST /api/config` → 200 и наблюдаемое состояние; совпадает с моим прогоном `sp._gate_state()`.
4. **F5 — закрыт.** Строка `HUMOR_CANDIDATE_EVAL_ENABLED` = **OFF** без делегирования (механизм написан/покрыт тестами, но вызовов в рантайме нет → включение без эффекта, релиз не блокируется); отдельный «F5-факт» для §21 отчёта, из шага 1 убраны env и SQL-запись оси; остатков «условно / IMPLEMENTED_AND_TESTED» в файле нет (grep — 0).
5. **Нит F2 — закрыт.** §6.3: «это выборка из общего PENDING-набора — агрегат §6.4», выборочных чисел в перечне нет.
6. **Таблица §4 цела**, конфликт-маркеров нет (0), файл читается без артефактов правки; порядок шагов включения/отката сохранён.

## Открытые условия включения осей (релизный гейт, задача parent/релизного лейна)

Precondition §5 не закрыт; ось включать только после:

- **(i)** — выполнено (11 withheld, effective чист).
- **(ii)** — снять read-only чтением прода и проверить контент `summary_editor` (2023) и per-chat `summary_cover_style` (110). В отчёте лейна этот шаг стоит в списке LIVE (§5.3) — по приоритету §5 он выполняется **до** включения; выявление расхождения — минимальный фикс или записанное решение parent.
- **(iii)** — по 4 Python-блокам: либо доказано отсутствие маркеров в реальных payload, либо находка + фикс до включения. Статус по отчёту: `internal.lore.story`/`internal.nostalgia.candidate` — вне 5 путей (F4 отчёта); `message.smartmodule.chat_persona` — **достижим в Direct** (`/persona`, F3 отчёта, AMD.4.6(iii)) и фикс предложен, но не сделан; `style.bot_knowledge` в отчёте отдельно не разобран.
- **Findings отчёта, подпадающие под директиву п.2** (общее правило §5/§7 «findings = условие включения» их уже покрывает; parent фиксирует решение по каждому): **F1** — достижимый оборот старого голоса в каноне Summary hybrid-L2 (`prompts.summary_l2_writer_system_prompt`, `flags.summary_hybrid_l2_enabled=true`); **F2** — код-канон/PREV-слепки на fallback-путях (PG-деградация, `SMART_VERBALIZER_MODES_ENABLED=0`; на проде триггеры не активны, env kill-switch снапшотом не снят — честная дырка); **F3** — `/persona` (user-visible); **F5** — контент `personas`/`persona_traits` (LIVE).

Рекомендация (не блокер): в §5 добавить явную строку, что severity-метки отчёта («related-nonblocking») не отменяют правила «findings = условие включения» — это снимет двусмысленность при закрытии precondition.

## Ledger R3

| Пункт задания | Статус |
|---|---|
| 1. F4a: ссылки на артефакты | VERIFIED |
| 2. F4b: критерии (i)(ii)(iii), источники | VERIFIED |
| 3. F4c: verify craft/инициативы | VERIFIED |
| 4. F5: OFF без делегирования, факт в отчёте | VERIFIED |
| 5. Нит F2 («выборка … агрегат §6.4») | VERIFIED |
| 6. §4 цела, файл чист | VERIFIED |
| Релизный гейт (payload-precondition) | OPEN — условия выше; не является дефектом препа |

Переиспользовано: стенд лейна (мои R2-хеши и репетиция совпали), review-fs (13/13 отпечатков), W7+FS прогоны. Вне этого лейна: живой прод-рестарт, `overview/gates` на сервере, read-only чтение двух кастомов и `personas`, Telegram-наблюдения.
