# AMD26 — покрытие путей клаузы SOUL-AMD.2.6 (сны/глубокий сон/рассказы о них/ностальгия/лор/истории/воспоминания)

Клауза: «Сны, глубокий сон, рассказы о них, ностальгия, лор, истории и
воспоминания — авторские тексты бота: получают Core и жанровые правила, а не
служебный нейтральный текст» (amendment §2.1, L00026).

Правило разбора: клауза дополняется §2.2 того же источника («Внутренние и
машинные стадии — без Core»); публикующим считается только текст, который
бот **публикует в чат от своего имени**. Классификация внутренних стадий
подтверждена review-w1 (dreams/lore/nostalgia/dossier: `speech=False`,
«§2.2 без Core, обосновано»).

| Путь клаузы | Human-facing текст? | Производитель → публикация | Состояние после слайса |
|---|---|---|---|
| **Ностальгия / воспоминания** | да — проактивное «кстати…» в тихом чате | `nostalgia_worker._llm_once` → `bot.send_message` (plain) / Initiative | проведено в W4 (`genre=nostalgia`, OFF — канон байт-в-байт). Не менялось |
| **Лор / истории (Летописец)** | да — «рассказ о лоре» публикуется в чат verbatim (safe-HTML) | `lore_compiler_service.compile` (канон `LORE_STORY_SYSTEM_PROMPT`) → `direct_chat_service` (`lore_compiled` / `lore_story`) | **проведено этим слайсом**: `authorial_system(writer="lore_writer", genre="lore")`; OFF — канон байт-в-байт, ON — Core + рамка «Лор» |
| **Лор — генерация авто-лора** | нет: текст профиля (данные), инжектится в контекст Direct; админ-витрина — не речь бота | `lore_worker` INIT/MERGE (`internal.lore.init/merge`) | не тронуто: внутренняя машинная стадия (§2.2), реестр `speech=False` |
| **Сны** | нет публикующего пути: убеждения пишутся в память (`graph_facts`), витрина TMA — данные | `dream_worker` distill (`internal.dream.distill`) | не тронуто (§2.2); рамка `genre.dream.rules` — Factory Default, готова к будущему пути |
| **Глубокий сон** | нет публикующего пути: парадигмы пишутся в память | `dream_worker` bridge (`internal.dream.deep_sleep_bridge`) | не тронуто (§2.2); рамка готова |
| **«Рассказы о них»** | нет: никто не рассказывает сон/парадигму в чат (поиск по репо: `send_message` с dream-текстом отсутствует) | — | не тронуто честно; контракт появления — `authorial_system(genre="dream")`, тест `test_dream_and_story_frames_stay_ready_contract` |
| **Истории чата (episodes/витрина TMA)** | витрина — данные для админа; извлечение/подтверждение — машинные стадии (JSON) | `mca_episodes` (`internal.episodes.*`), `web/api/stories.py` | не тронуто: не публичная речь бота |
| **Творческие тексты** | отдельного публикующего пути с собственным каноном нет (творческий текст в Direct идёт через Core канала, AMD.2.3) | — | не тронуто; `genre.story.rules` — Factory Default, готова |

## Проверки

- Поиск публикующих путей: `send_message`/`send_text` в
  `dream_worker.py`, `lore_worker.py`, `mca_dream_history.py`,
  `mca_dream_evidence.py` — совпадений нет; публикация Летописца —
  единственная точка выхода lore-контура в чат (`direct_chat_service.py`
  «при `ctx.lore_compiled` доставляем ГОТОВЫЙ текст истории»).
- Реестр: `internal.dream.distill/deep_sleep_bridge/lore.init/lore.merge` —
  `speech=False` (`test_untouched_machine_stages_are_marked_in_registry`).
- Проводка: OFF-паритет и ON-применение жанра на реальном пути —
  `tests/test_soul1_amd26_authorial_wiring.py` (6 тестов);
  мутации склеек — `evidence/amd26/mutation-witness.json` (6/6 KILLED).
