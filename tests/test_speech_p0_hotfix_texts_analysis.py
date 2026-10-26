"""SPEECH-P0-A1 (25.10.2026) — точные тексты §2 и поведение анализа §3.

Доказывает по `plans/features/asap-speech-arch/source-owner-p0-hotfix-
2026-10-25.md`:
* §2 — пять runtime-директив (BASE/HUMOR/LENGTH/FREQUENT/FACTUAL) совпадают
  с текстами владельца БАЙТ-В-БАЙТ; OFF/OCCASIONAL не тронуты;
* §3 — писательская инструкция разбора больше не заказывает эссе: прямой
  ответ первым, релевантные наблюдения, материал можно сжимать и
  перестраивать, нет обязательной хроники/псих-эссе/стендапа и жёсткого
  шаблона, подробности по запросу, отсутствие данных не выдумывается;
* краткость не достигается техническим обрезанием (нет лимитов/постпроцесса).

TEST-LIFECYCLE: CONTRACT owner=SPEECH-P0-A1/§2/§3
"""
from __future__ import annotations

from services import mca_expression as ex
from services import prompt_style_blocks as psb
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Независимые литералы §2 (source §2, blockquote-строки) — тест ловит любое
# изменение runtime-константы.
BASE_SPEECH = (
    "Разговаривай естественно, как обычный участник чата. Отвечай сразу по "
    "существу. Не растягивай простые мысли, не превращай ответы в рассказы "
    "и не демонстрируй характер специально. Подробности добавляй, когда они "
    "действительно нужны."
)
HUMOR = (
    "Шути спонтанно, когда это уместно. Не вымучивай панчлайны, не строй "
    "истории ради шутки, не пытайся быть смешной в каждом сообщении. Не "
    "объясняй собственный юмор."
)
RESPONSE_LENGTH = (
    "Длина ответа зависит от вопроса. Иногда достаточно двух слов, иногда "
    "нужен подробный разбор. Не повторяй сказанное и заканчивай, когда "
    "мысль закончена."
)
PROFANITY_FREQUENT = (
    "Матерись часто и естественно, как в обычном грубом интернет-разговоре. "
    "Не выдумывай сложные ругательные конструкции и не вставляй мат "
    "механически."
)
FACTUAL = (
    "Не выдавай придуманные события, даты, цитаты и статистику за реальные. "
    "Если фактов недостаточно, не достраивай историю фантазией. Шути и "
    "преувеличивай свободно, но не подменяй этим реальные воспоминания."
)


# ── §2: точные тексты ──────────────────────────────────────────────────────

def test_five_runtime_texts_are_owner_texts_byte_for_byte():
    assert ex.BASE_SPEECH_TEXT == BASE_SPEECH
    assert ex.HUMOR_TEXT == HUMOR
    assert ex.RESPONSE_LENGTH_TEXT == RESPONSE_LENGTH
    assert ex.PROFANITY_FREQUENT_TEXT == PROFANITY_FREQUENT
    assert ex.FACTUAL_SPEECH_TEXT == FACTUAL
    assert ex.PROFANITY_INSTRUCTIONS["frequent"] == PROFANITY_FREQUENT


def test_off_and_occasional_are_not_changed():
    """§2: OFF/OCCASIONAL сохраняются по ранее утверждённым текстам."""
    assert ex.PROFANITY_OFF_TEXT == (
        "Не используй мат в собственной речи. Цитаты и исходные "
        "пользовательские данные не переписывай ради этого правила.")
    assert ex.PROFANITY_OCCASIONAL_TEXT == (
        "Матерись иногда, когда это естественно вписывается в разговор. Не "
        "добавляй ругательства специально и не делай их обязательной частью "
        "каждого ответа.")


def test_old_verbose_wordings_are_not_runtime():
    """Прежние многословные формулировки остались только слепками."""
    runtime = "\n".join((
        ex.BASE_SPEECH_TEXT, ex.HUMOR_TEXT, ex.RESPONSE_LENGTH_TEXT,
        ex.PROFANITY_FREQUENT_TEXT, ex.FACTUAL_SPEECH_TEXT))
    for stale in ("без воды и искусственной драматургии",
                  "не превращай ответы в стендап",
                  "непринуждённо, как человек, для которого мат",
                  "притворяйся очевидцем"):
        assert stale not in runtime, stale
    assert ex.PREV_BASE_SPEECH_TEXT != ex.BASE_SPEECH_TEXT
    assert ex.PREV_HUMOR_TEXT != ex.HUMOR_TEXT
    assert ex.PREV_RESPONSE_LENGTH_TEXT != ex.RESPONSE_LENGTH_TEXT
    assert ex.PREV_FACTUAL_SPEECH_TEXT != ex.FACTUAL_SPEECH_TEXT
    assert ex.PREV_P0E_PROFANITY_FREQUENT_TEXT != ex.PROFANITY_FREQUENT_TEXT


def test_no_instruction_quotas_for_speech_texts():
    """§6: краткость не реализуется квотами/обрезанием."""
    for text in (BASE_SPEECH, HUMOR, RESPONSE_LENGTH, PROFANITY_FREQUENT,
                 FACTUAL):
        assert "%" not in text
        assert not any(ch.isdigit() for ch in text)


# ── §3: разбор не заказывает эссе ──────────────────────────────────────────

def test_analysis_writer_instruction_has_no_essay_order():
    block = psb.MODE_DEEP_RESEARCH_BLOCK
    low = block.casefold()
    # Прежний приказ «выведи отчёт ПОЛНОСТЬЮ, ничего не сжимай» снят.
    assert "полностью, ничего не" not in low
    assert "ничего не выбрасывай и не сжимай" not in low
    # Обязательных объёмов/структуры эссе больше нет.
    for banned in ("не менее", "минимум абзац", "четыре абзац", "4 абзац",
                   "архетип", "обязательн", "рекомендаци"):
        assert banned not in low, banned


def test_analysis_writer_instruction_keeps_owner_principles():
    block = psb.MODE_DEEP_RESEARCH_BLOCK
    low = block.casefold()
    # Дословно из source-owner-p0-hotfix-addendum-2026-10-25.md §1.
    assert "Проанализируй доступные сведения по существу вопроса." in block
    assert "Отвечай прямо, естественно и соразмерно запросу." in block
    assert "Используй наиболее релевантные подтверждённые наблюдения." in block
    assert ("Не превращай простой вопрос в психологическое эссе, хронологию "
            "событий или художественный рассказ.") in block
    assert "Подробный анализ проводи, когда его действительно просят." in block
    assert ("Не придумывай факты, даты, диалоги и причинные связи."
            in block)
    assert ("Используй результаты анализа для ответа на вопрос, но не "
            "пересказывай внутреннюю структуру анализа.") in block
    assert ("Сохраняй существенные факты и выводы, не добавляя "
            "неподтверждённых подробностей.") in block
    assert "длину внешнего ответа" in low
    # Жёсткого шаблона/обязательного объёма нет.
    for banned in ("не менее", "минимум абзац", "архетип", "обязательн",
                   "рекомендаци", "выведи переданный"):
        assert banned not in low, banned


def test_previous_analysis_block_is_kept_as_rollback_snapshot():
    prev = psb.PREV_MODE_DEEP_RESEARCH_BLOCK
    assert "ничего не" in prev and "не сжимай" in prev
    assert prev != psb.MODE_DEEP_RESEARCH_BLOCK


def test_analysis_texts_are_owner_addendum_byte_for_byte():
    """§1 аддендума 25.10.2026: целевая инструкция анализа и замена
    требования «сохрани структуру» — дословно, без пересказа."""
    src = (ROOT / "plans" / "features" / "asap-speech-arch" /
           "source-owner-p0-hotfix-addendum-2026-10-25.md"
           ).read_text(encoding="utf-8")
    quoted = [line.strip()[1:-1] for line in src.splitlines()
              if line.startswith('"') and line.endswith('"')]
    analysis_text = next(q for q in quoted
                         if q.startswith("Проанализируй доступные сведения"))
    writer_text = next(q for q in quoted
                       if q.startswith("Используй результаты анализа"))
    block = psb.MODE_DEEP_RESEARCH_BLOCK
    assert analysis_text in block
    assert writer_text in block
    assert "сохрани структур" not in block.casefold()
    assert "сохранить структур" not in block.casefold()
    assert "не сжимай" not in block.casefold()
    # Суть сохранена: внутреннюю структуру анализа не пересказывать.
    assert "структуру" in writer_text


def test_analysis_block_reaches_writer_payload_without_duplication():
    system = psb.compose_verbalizer_system(
        "КАНАЛ: технический контракт.", "deep_research", "rich",
        html_safe=True)
    assert system.count(psb.MODE_DEEP_RESEARCH_BLOCK) == 1
    # Прямой ответ не теряется: инструкция идёт в систему целиком.
    assert "Отвечай прямо, естественно и соразмерно запросу." in system
