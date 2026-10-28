"""P0-HA QUALITY (волна 4b, снапшот 2026-10-29 §12-§13) — качество анализа
участников и событий: детерминированные страховки claim_envelope +
инструкционные блоки prompt_style_blocks.

Покрытие: различение типов материала (REQ-HA-QUALITY-CLASSIFY), единичная
шутка/реплика не становится устойчивой характеристикой (строка 469),
пересылка приписана исходному автору, а не переславшему (H26), похожие
имена разных участников не сливаются — identity по Telegram user_id
(волна 4: uid — первичный ключ, ref сообщения — не личность; H25),
значимые утверждения трассируются до refs выборки (REQ-HA-CLAIMS-TRACE),
количества и даты не придумываются (REQ-HA-NO-INVENTED-STATS), собственные
высказывания бота — материал выборки на общих правилах, не авто-правда.
Без сети, без БД; тексты сообщений в логи/утверждения не попадают.
"""
import datetime

from services.canonical_context import format_context_item
from services.claim_envelope import (
    FINDING_KIND_BOT_STATEMENT,
    FINDING_KIND_BRIEF_EVENT,
    FINDING_KIND_DISPUTE,
    FINDING_KIND_EXTERNAL_NEWS,
    FINDING_KIND_FORWARDED,
    FINDING_KIND_JOKE,
    FINDING_KIND_PARTICIPANT_CLAIM,
    FINDING_KIND_REPEAT_THEME,
    FINDING_KIND_SINGLE_REMARK,
    attribution_conflict,
    classify_finding_kind,
    finding_attribution_owner,
    identity_matches,
    invented_count_violations,
    invented_date_violations,
    parse_finding_identity,
    stable_trait_claim_allowed,
    validate_finding_refs,
)
from services.prompt_style_blocks import (
    HISTORY_COVERAGE_ASSEMBLY_BLOCK,
    HISTORY_EXTRACTION_QUALITY_BLOCK,
)

CHAT_ID = -1001234567890
TS_29_OCT = int(datetime.datetime(
    2026, 10, 29, 12, 0, tzinfo=datetime.timezone.utc).timestamp())


# ── инструкции (prompt-contract) ────────────────────────────────────────────

class TestExtractionInstructions:
    """Извлечение фактов из сегмента различает типы материала (§12)."""

    def test_all_nine_kinds_named(self):
        block = HISTORY_EXTRACTION_QUALITY_BLOCK
        for label in ("повторяющ", "спор", "краткое событие",
                      "единичн", "шутк", "переслан", "новост",
                      "утверждение", "высказывание бота"):
            assert label in block, label

    def test_single_joke_not_a_trait(self):
        block = HISTORY_EXTRACTION_QUALITY_BLOCK
        assert "Единичную реплику или шутку не описывай как устойчивую" \
               in block

    def test_forwarded_attribution_to_original_author(self):
        block = HISTORY_EXTRACTION_QUALITY_BLOCK
        assert "Переслано" in block
        assert "исходного автора" in block
        assert "не того, кто переслал" in block

    def test_no_invented_counts_dates_order(self):
        block = HISTORY_EXTRACTION_QUALITY_BLOCK
        assert "Не придумывай количество, частоту, даты" in block
        assert "порядок событий" in block

    def test_refs_required_for_events(self):
        block = HISTORY_EXTRACTION_QUALITY_BLOCK
        assert "refs ставь на те сообщения" in block

    def test_bot_statements_same_evidencing_rules(self):
        block = HISTORY_EXTRACTION_QUALITY_BLOCK
        assert "Собственные высказывания бота" in block
        assert "не как уже проверенную правду" in block

    def test_no_topic_or_name_exceptions(self):
        """H27/H30: инструкции без конкретных тем/имён/словарных
        исключений."""
        for block in (HISTORY_EXTRACTION_QUALITY_BLOCK,
                      HISTORY_COVERAGE_ASSEMBLY_BLOCK):
            assert "Внуково" not in block
            assert "400" not in block and "2000" not in block


class TestAssemblyInstructions:
    """Финальная сборка ответа опирается на накопленные находки (§13)."""

    def test_all_nine_kinds_named(self):
        block = HISTORY_COVERAGE_ASSEMBLY_BLOCK
        for label in ("повторяющиеся темы", "продолжительные споры",
                      "краткие события", "единичные реплики", "шутки",
                      "пересланные публикации", "внешние новости",
                      "утверждения", "высказывания бота"):
            assert label in block, label

    def test_no_invented_actions(self):
        block = HISTORY_COVERAGE_ASSEMBLY_BLOCK
        assert "только действия и слова, которые видны в сообщениях" in block

    def test_claims_rest_on_coverage_events(self):
        block = HISTORY_COVERAGE_ASSEMBLY_BLOCK
        assert "@@HISTORY_COVERAGE" in block
        assert "опирай на события" in block

    def test_no_details_for_coherence(self):
        block = HISTORY_COVERAGE_ASSEMBLY_BLOCK
        assert "не добавляй детали ради связности" in block

    def test_no_invented_statistics(self):
        block = HISTORY_COVERAGE_ASSEMBLY_BLOCK
        assert "статистику не придумывай" in block

    def test_similar_names_not_merged(self):
        block = HISTORY_COVERAGE_ASSEMBLY_BLOCK
        assert "Похожие имена разных участников не объединяй" in block

    def test_bot_statements_not_auto_truth(self):
        block = HISTORY_COVERAGE_ASSEMBLY_BLOCK
        assert "не автоматически достоверные факты" in block


# ── тип находки ─────────────────────────────────────────────────────────────

class TestClassifyFindingKind:
    def test_forward_flag_wins_over_markers(self):
        assert classify_finding_kind("новость о погоде", is_forward=True) \
            == FINDING_KIND_FORWARDED

    def test_bot_author_kind(self):
        assert classify_finding_kind("рассказал про погоду",
                                     is_bot_author=True) \
            == FINDING_KIND_BOT_STATEMENT
        # пересылка структурно сильнее авторства бота: содержание — чужое
        assert classify_finding_kind("переслал анонс", is_forward=True,
                                     is_bot_author=True) \
            == FINDING_KIND_FORWARDED

    def test_news_markers(self):
        assert classify_finding_kind("новость о задержке рейсов") \
            == FINDING_KIND_EXTERNAL_NEWS
        assert classify_finding_kind("статья из СМИ") \
            == FINDING_KIND_EXTERNAL_NEWS

    def test_joke_markers(self):
        assert classify_finding_kind("объяснение было шуткой") \
            == FINDING_KIND_JOKE
        assert classify_finding_kind("сказал с сарказмом") \
            == FINDING_KIND_JOKE

    def test_dispute_markers(self):
        assert classify_finding_kind("поспорили о религии") \
            == FINDING_KIND_DISPUTE
        assert classify_finding_kind("разногласия по срокам") \
            == FINDING_KIND_DISPUTE

    def test_repeat_markers(self):
        assert classify_finding_kind("снова вернулся к теме ремонта") \
            == FINDING_KIND_REPEAT_THEME
        assert classify_finding_kind("повторяющийся вопрос о отпуске") \
            == FINDING_KIND_REPEAT_THEME

    def test_claim_markers(self):
        assert classify_finding_kind("заявил, что проект закрыт") \
            == FINDING_KIND_PARTICIPANT_CLAIM
        assert classify_finding_kind("по его словам всё хорошо") \
            == FINDING_KIND_PARTICIPANT_CLAIM

    def test_single_remark_markers(self):
        assert classify_finding_kind("единичная реплика про кофе") \
            == FINDING_KIND_SINGLE_REMARK

    def test_fallback_by_ref_count(self):
        assert classify_finding_kind("обсуждение погоды",
                                     distinct_refs=1) \
            == FINDING_KIND_SINGLE_REMARK
        assert classify_finding_kind("обсуждение погоды",
                                     distinct_refs=3) \
            == FINDING_KIND_BRIEF_EVENT
        assert classify_finding_kind("обсуждение погоды") \
            == FINDING_KIND_SINGLE_REMARK


# ── запрет обобщений (строка 469) ───────────────────────────────────────────

class TestTraitEscalationGuard:
    def test_joke_never_a_trait_even_with_refs(self):
        assert stable_trait_claim_allowed(FINDING_KIND_JOKE, 5) is False

    def test_single_remark_never_a_trait(self):
        assert stable_trait_claim_allowed(FINDING_KIND_SINGLE_REMARK, 1) \
            is False

    def test_forwarded_news_bot_not_trait_kinds(self):
        for kind in (FINDING_KIND_FORWARDED, FINDING_KIND_EXTERNAL_NEWS,
                     FINDING_KIND_BOT_STATEMENT,
                     FINDING_KIND_PARTICIPANT_CLAIM,
                     FINDING_KIND_BRIEF_EVENT):
            assert stable_trait_claim_allowed(kind, 4) is False, kind

    def test_repeat_theme_needs_two_distinct_refs(self):
        assert stable_trait_claim_allowed(FINDING_KIND_REPEAT_THEME, 1) \
            is False
        assert stable_trait_claim_allowed(FINDING_KIND_REPEAT_THEME, 2) \
            is True

    def test_dispute_needs_two_distinct_refs(self):
        assert stable_trait_claim_allowed(FINDING_KIND_DISPUTE, 1) is False
        assert stable_trait_claim_allowed(FINDING_KIND_DISPUTE, 3) is True

    def test_unknown_kind_conservative(self):
        assert stable_trait_claim_allowed("неведомый-тип", 10) is False


# ── атрибуция пересылок (H26) ───────────────────────────────────────────────

class TestForwardedAttribution:
    def _forward_line(self):
        # реальный канонический рендер format_context_item
        return format_context_item(
            ts=TS_29_OCT, author="Вася", item_id="tg:42",
            forward_source="РБК Новости", text="Курс обновлён",
            kind="msg")

    def test_canonical_line_marks_forward(self):
        line = self._forward_line()
        assert "Переслано: РБК Новости" in line
        assert line.startswith("[")

    def test_identity_parsed(self):
        identity = parse_finding_identity(self._forward_line())
        assert identity.is_forward is True
        assert identity.display_name == "Вася"
        assert identity.ref == "tg:42"
        assert identity.forward_source == "РБК Новости"

    def test_owner_is_original_author_not_forwarder(self):
        identity = parse_finding_identity(self._forward_line())
        assert finding_attribution_owner(identity) == "РБК Новости"

    def test_forwarder_credited_is_conflict(self):
        identity = parse_finding_identity(self._forward_line())
        # «Вася сообщил курс...» — содержание приписано переславшему (H26)
        assert attribution_conflict("Вася сообщил про курс", identity) \
            is True
        # исходный автор назван — конфликта нет
        assert attribution_conflict("РБК Новости сообщило курс", identity) \
            is False

    def test_regular_line_owner_is_author(self):
        line = format_context_item(ts=TS_29_OCT, author="Аня",
                                   item_id="tg:7", text="Привет",
                                   kind="msg")
        identity = parse_finding_identity(line)
        assert identity.is_forward is False
        assert identity.forward_source == ""
        assert finding_attribution_owner(identity) == "Аня"
        assert attribution_conflict("Аня сказала привет", identity) is False

    def test_unmarked_line_gives_empty_identity(self):
        identity = parse_finding_identity("просто текст без разметки")
        assert identity.ref == ""
        assert identity.display_name == ""
        assert finding_attribution_owner(identity) == ""

    def test_word_boundary_no_false_conflict(self):
        """«Вася» не совпадает с «Василиса» по границе слова."""
        identity = parse_finding_identity(self._forward_line())
        assert attribution_conflict("Василиса прислала новость",
                                    identity) is False


# ── идентичность по Telegram user id (H25, волна 4: uid — первичный ключ) ───

class TestIdentityByRef:
    def test_same_display_name_different_uids_not_merged(self):
        """Два «Алексея» с разными user_id — разные участники, сколько бы
        сообщений ни было (строка 475: uid — первичная идентичность)."""
        line_a = format_context_item(ts=TS_29_OCT, author="Алексей [111]",
                                     item_id="tg:11", text="я за",
                                     kind="msg")
        line_b = format_context_item(ts=TS_29_OCT, author="Алексей [222]",
                                     item_id="tg:22", text="я против",
                                     kind="msg")
        a, b = parse_finding_identity(line_a), parse_finding_identity(line_b)
        assert a.user_id == 111 and b.user_id == 222
        assert a.display_name == b.display_name == "Алексей"
        assert identity_matches(a, b) is False

    def test_same_uid_two_messages_is_one_person(self):
        """Два сообщения одного uid — один человек (ref сообщения — не
        личность: сравнение по message id давало ложное «разные»)."""
        line_a = format_context_item(ts=TS_29_OCT, author="Алексей [111]",
                                     item_id="tg:11", text="я за",
                                     kind="msg")
        line_b = format_context_item(ts=TS_29_OCT, author="Алексей [111]",
                                     item_id="tg:22", text="и ещё раз",
                                     kind="msg")
        a, b = parse_finding_identity(line_a), parse_finding_identity(line_b)
        assert a.user_id == b.user_id == 111
        assert a.ref != b.ref
        assert identity_matches(a, b) is True

    def test_same_display_name_different_refs_not_merged(self):
        """Без uid (строки без разметки user_id) — совместимый падение на
        сравнение ref сообщения: разные ref — разные участники."""
        line_a = format_context_item(ts=TS_29_OCT, author="Алексей",
                                     item_id="tg:11", text="я за",
                                     kind="msg")
        line_b = format_context_item(ts=TS_29_OCT, author="Алексей",
                                     item_id="tg:22", text="я против",
                                     kind="msg")
        ref_a = parse_finding_identity(line_a).ref
        ref_b = parse_finding_identity(line_b).ref
        assert ref_a == "tg:11" and ref_b == "tg:22"
        assert identity_matches(ref_a, ref_b) is False

    def test_same_ref_is_same_identity(self):
        assert identity_matches("tg:11", "tg:11") is True

    def test_empty_ref_establishes_nothing(self):
        assert identity_matches("", "tg:11") is False
        assert identity_matches(None, None) is False

    def test_msg_and_fact_refs_distinct(self):
        assert identity_matches("msg:5", "fact:5") is False


# ── трассировка утверждений (§13) ───────────────────────────────────────────

class TestRefTraceability:
    def test_out_of_sample_refs_dropped(self):
        kept, dropped = validate_finding_refs(
            ["tg:1", "tg:999", "tg:2"], {"tg:1", "tg:2"})
        assert kept == ["tg:1", "tg:2"]
        assert dropped == ["tg:999"]

    def test_order_preserved_and_blanks_skipped(self):
        kept, dropped = validate_finding_refs(
            ["tg:3", "", "tg:1"], {"tg:1", "tg:3"})
        assert kept == ["tg:3", "tg:1"]
        assert dropped == []

    def test_empty_known_refs_drop_everything(self):
        kept, dropped = validate_finding_refs(["tg:1"], set())
        assert kept == [] and dropped == ["tg:1"]

    def test_events_without_refs_not_traceable(self):
        """Событие без refs не даёт подтверждения утверждениям."""
        kept, _ = validate_finding_refs([], {"tg:1"})
        assert kept == []


# ── запрет придуманной статистики/дат (§13 строка 487) ─────────────────────

class TestNoInventedStats:
    def test_count_beyond_refs_is_violation(self):
        assert invented_count_violations("обсуждали 5 раз",
                                         distinct_ref_count=2) == [5]

    def test_count_within_refs_ok(self):
        assert invented_count_violations("обсуждали 2 раза",
                                         distinct_ref_count=2) == []
        assert invented_count_violations("обсудили 1 раз",
                                         distinct_ref_count=2) == []

    def test_no_numbers_no_violation(self):
        assert invented_count_violations("несколько раз обсуждали", 1) == []

    def test_zero_refs_any_count_is_violation(self):
        assert invented_count_violations("3 сообщения подряд", 0) == [3]

    def test_supported_date_ok(self):
        ts_by_ref = {"tg:1": TS_29_OCT, "tg:2": TS_29_OCT}
        assert invented_date_violations("29.10.2026 случился срыв",
                                        ts_by_ref) == []

    def test_unsupported_date_is_violation(self):
        ts_by_ref = {"tg:1": TS_29_OCT}
        assert invented_date_violations("15.03.2025 была встреча",
                                        ts_by_ref) == ["15.03.2025"]

    def test_adjacent_day_within_tz_tolerance(self):
        """±1 сутки — допуск локального сдвига чата без чтения tz."""
        ts_by_ref = {"tg:1": TS_29_OCT}
        assert invented_date_violations("30.10.2026 продолжили тему",
                                        ts_by_ref) == []
        assert invented_date_violations("28.10.2026 начали тему",
                                        ts_by_ref) == []

    def test_note_without_dates_ok(self):
        assert invented_date_violations("обсуждали релиз",
                                        {"tg:1": TS_29_OCT}) == []

    def test_non_calendar_numbers_not_dates(self):
        """«2.10» (версия/доля) — не календарная дата, гард молчит."""
        assert invented_date_violations("версия 2.10 вышла",
                                        {"tg:1": TS_29_OCT}) == []

    def test_unsupported_nonpadded_dates_flagged_as_written(self):
        """Неприбитые нулём формы (блокер B review-w4-fix): флаг несёт
        ТОЧНОЕ написание из note, не нормализованную запись — строка
        флага совпадает с тем, что срезается из note."""
        ts_by_ref = {"tg:1": TS_29_OCT}
        assert invented_date_violations(
            "5.10.2024 была встреча", ts_by_ref) == ["5.10.2024"]
        assert invented_date_violations(
            "15.3.2025 была встреча", ts_by_ref) == ["15.3.2025"]
        assert invented_date_violations(
            "5.3.2025 была встреча", ts_by_ref) == ["5.3.2025"]

    def test_mixed_padding_writings_flagged_separately(self):
        """Оба написания одной даты в одной note — два разных среза в
        порядке обнаружения (у каждого своё написание)."""
        ts_by_ref = {"tg:1": TS_29_OCT}
        assert invented_date_violations(
            "5.10.2024 и 05.10.2024",
            ts_by_ref) == ["5.10.2024", "05.10.2024"]

    def test_nonpadded_date_supported_by_stamp_not_flagged(self):
        """Дата, которую подтверждает штамп ref, не помечается — и в
        неприбитой форме тоже (сравнение по календарному дню)."""
        ts = int(datetime.datetime(
            2024, 10, 5, 12, 0, tzinfo=datetime.timezone.utc).timestamp())
        assert invented_date_violations(
            "5.10.2024 была встреча", {"tg:1": ts}) == []

    def test_non_calendar_full_numeric_not_dates(self):
        """Некалендарные полные тройки (32.13.2024) — гард молчит."""
        assert invented_date_violations(
            "32.13.2024 была встреча", {"tg:1": TS_29_OCT}) == []


# ── бот на общих правилах выборки ───────────────────────────────────────────

class TestBotStatementsEvidenceEquivalence:
    def test_bot_lines_classified_and_gated(self):
        kind = classify_finding_kind("подтвердил, что всё работает",
                                     distinct_refs=2, is_bot_author=True)
        assert kind == FINDING_KIND_BOT_STATEMENT
        # авто-правды нет: даже подтверждение бота — не «устойчивая черта»
        assert stable_trait_claim_allowed(kind, 2) is False
        assert stable_trait_claim_allowed(kind, 5) is False

    def test_bot_forward_follows_forward_rules(self):
        """Пересылка от бота — содержание исходного автора (H26), не бота."""
        line = format_context_item(ts=TS_29_OCT, author="AsapBot",
                                   item_id="tg:77",
                                   forward_source="Погодный канал",
                                   text="Штормовое предупреждение",
                                   kind="msg")
        identity = parse_finding_identity(line)
        assert finding_attribution_owner(identity) == "Погодный канал"
        assert attribution_conflict("AsapBot предупредил о шторме",
                                    identity) is True
        assert attribution_conflict(
            "Погодный канал предупредил о шторме", identity) is False

    def test_bot_note_stats_same_guards(self):
        assert invented_count_violations(
            "бот писал 9 раз", distinct_ref_count=2) == [9]
