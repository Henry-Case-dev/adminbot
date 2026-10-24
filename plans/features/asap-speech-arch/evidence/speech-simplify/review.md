# Ревью кандидата `e44a30b4` (раунд 4, финальное) — P0 SPEECH-SIMPLIFY

LANE_ID: REVIEW-SPEECH-SIMPLIFY
Кандидат: `e44a30b47827439d477644b68e26a0b4aa3eddbf` (`origin/task/speech-simplify-final`).
Дельта: `91935804..e44a30b4` (5 файлов). Прошлые ревью: `88bdedfe`, `dce41eea`, `8cb2a8f7`.
Режим: read-only, без прода/SSH. 2026-10-25, +12:00.

## ВЕРДИКТ: **Approved**

## Проверено

1. **4 прежних падения закрыты, нормализация ограничена суффиксом.** В `tests/test_cfg07_backstage_contract.py:290` добавлена подстановка `PREV_SPEECH_STYLE_SUFFIX → STYLE_BLOCKS_SUFFIX` перед строгим сравнением; остальные байты канона по-прежнему сравниваются без поблажек. Прогон 8 профильных файлов: **214 passed** (в т.ч. `test_cfg07_backstage_contract`, `test_cfg07a_f1_custom_suppress`, `test_p0_prompts_core`, `test_expression_isolation_followup`, `test_direct_chat_prompts`, `test_checkup_prompts`).
2. **Humor guard/technique — только запрет объяснять, без возврата обязательных приёмов.** `HUMOR_CRAFT_GUARD`: «Приём уместен, только если ситуация располагает. Не растягивай шутку. **Не объясняй шутку и не называй приём.** Факты… неприкосновенны»; `HUMOR_TECHNIQUE_DEADPAN`: «…**Ничего не объясняй и не подсказывай, что это шутка.**» Кульминации, квот, «обязательно», «комбинируй», процентов нет; все 5 техник ≤183 c. `HUMOR_TEXT` (владельческая короткая директива) не менялся.
3. **Отпечаток соответствует пересчёту.** `factory_set_fingerprint() == FACTORY_SET_SHA256_12 == "f12130fbccb1"` (`services/prompt_registry.py:1702`); пины обновлены ровно в трёх тестах (`test_expression_isolation_followup.py:150`, `test_p0_prompts_core.py:90`), подделок нет.
4. **Активные каноны и B/C payload не менялись.** В дельте нет правок `prompt_composer.py`, `prompt_style_blocks.py`, активных канонов search/summary/chat/checkup — только humor-тексты и отпечаток. Humor-craft в пробах выключен, поэтому B/C payload идентичен `91935804`.
5. **Широкий прогон воспроизведён:** `pytest tests --ignore=tests/js -k "speech or expression or prompt or checkup or factcheck or unified_core or cfg07"` → **1668 passed**, 0 failed (36 s).

## Nonblocking

1. Журнал бампов над `FACTORY_SET_SHA256_12` снова не дополнен строкой про `f12130fbccb1` и причину (правка humor-текстов) — нарушение принятой трассировки, не влияет на поведение.
2. Полный `pytest tests` в раунде 3 давал 44 падения UI/БД/стартовых миграций — это среда/не связанные модули; в этот прогон они не входят. Для релиза нужен либо baseline-прогон, либо явный список известных падений (процессное, не код).
3. Нормализация суффикса в двух тестах исключает регион суффикса из их сравнения; сам суффикс покрыт sha-пинами Checkup и эталонами активных канонов.

## Осталось на пробы (вне роли Reviewer)

B/C payload уже снят (22 вызова): краткость, серьёзная тема без иронии, устойчивость FREQUENT vs baseline 3/6 и 1/4, DVACH × OFF/OCCASIONAL/FREQUENT, формат checkup/summary/factcheck после `Speech_Base`. Прод-деплой и healthcheck — DevOps.

## Как проверялось

Дифф `91935804..HEAD`; прогон 8 профильных файлов (214 passed) и широкого `-k`-набора (1668 passed); сверка `factory_set_fingerprint()` с константой; проверка текстов humor-guard/technique на запрещённые маркеры; проверка, что composer и активные каноны не менялись. Прод/SSH/LLM не использовались.
