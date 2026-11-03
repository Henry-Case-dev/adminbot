"""EVOL-REPLY-CONTEXT-INTEGRITY-01 v5 — шов речевой проекции (Lane A).

Контракт: ``plans/features/evol/arch/reply-context-integrity-v5-contract.md``
§3/§4.2 (одна структура — две проекции), §4.3 п.3–4 (метки как адресная
разметка, явные отношения), §4.4 (CONTEXT-FIDELITY: ничего семантического не
теряется), §4.5/§9.4 (run-манифест: представление + типы полей, без текстов).
Источник требований: ``plans/owner_inputs/2026-11-03-evol-reply-context-integrity-v5.md``
§5.4, §9.2–§9.5, §13 сц. 53–70, 97–120.

Проверяется наблюдаемое поведение шва, а не внутренности:
  * машинная сторона (`format_context_item`/`format_chain_line`/`resolve_item_id`)
    остаётся сырой — L1/планировщик/retrieval/dedup/attribution не теряют ID;
  * речевая сторона (`format_speech_item`/`render_speech_line`/
    `render_reply_chains`/`media_marker(projection=...)`) отдаёт стабильные
    метки с обратным отображением, но сохраняет время, автора, forward,
    цитату с автором и Reply-край;
  * `flags.context_speech_projection` — единственный горячий рубильник.

TEST-LIFECYCLE: CONTRACT (owner=EVOL-REPLY-CONTEXT-INTEGRITY-01 v5, Lane A).
"""
import pytest

from config.settings import Settings
from services import canonical_context as cc
from services import hot_config
from services import mca_events
from services import thread_chain
from services.canonical_context import (
    RELATION_REPLY,
    RELATION_SEMANTIC,
    REPRESENTATION_INTERNAL,
    SPEECH_RELATION_MISSING_EDGE,
    SpeechProjection,
    SpeechQuote,
    SpeechRelation,
    format_context_item,
    format_speech_item,
    resolve_item_id,
    speech_projection_enabled,
)
from services.media_marker import MEDIA_MARKER_RE, media_marker
from services.target_marking import TARGET_MARKER_CORE, TARGET_MARKER

CHAT_ID = -1007001
# Время проверяется абсолютное: 30.04.2024 16:00 UTC.
TS_ROOT = 1_714_492_800
TS_STEP = 60


# ── фикстуры/стабы ──────────────────────────────────────────────────────────

def _row(**kw):
    data = {"user_id": 10, "author_name": "Вася", "text": "привет",
            "timestamp": TS_ROOT, "tg_message_id": 100, "id": 900,
            "media_type": "text", "is_forward": 0, "reply_to_id": None,
            "forward_source": None, "quote_text": None,
            "quote_author_id": None, "quote_position": None,
            "quote_is_manual": None}
    data.update(kw)
    return data


class _FakeChainDB:
    def __init__(self, messages, bot_replies=None, parents=None):
        self.messages = messages
        self.bot_replies = bot_replies or {}
        self.parents = parents or {}

    async def get_smart_message_by_tg_id(self, chat_id, tg_id):
        return self.messages.get(tg_id)

    async def get_bot_reply(self, chat_id, tg_id, now):
        return self.bot_replies.get(tg_id)

    async def get_bot_reply_parent(self, chat_id, tg_id, now):
        return self.parents.get(tg_id)


class _Cache:
    """Минимальный ConfigCache-совместимый стаб для hot-ключа."""

    def __init__(self, values):
        self.values = dict(values)

    def get(self, key, default=None):
        return self.values.get(key, default)


@pytest.fixture
def hot_cache():
    saved = hot_config.get_config_cache()

    def install(values):
        hot_config.set_config_cache(_Cache(values))

    yield install
    hot_config.set_config_cache(saved)


# ── E1/E3: метки и обратная карта ───────────────────────────────────────────

class TestLabelsAndReverseMap:
    def test_labels_are_stable_within_run_and_reverse_mapped(self):
        """§4.3 п.3/п.5: метка один раз на прогон, обратная карта точна."""
        projection = SpeechProjection(run_id="run-a")
        first = format_speech_item(
            ts=TS_ROOT, author="Вася", author_uid=10, item_id="tg:100",
            text="первое", projection=projection)
        again = format_speech_item(
            ts=TS_ROOT, author="Вася", author_uid=10, item_id="tg:100",
            text="первое", projection=projection)
        second = format_speech_item(
            ts=TS_ROOT + TS_STEP, author="Вася", author_uid=10,
            item_id="tg:101", text="второе", projection=projection)

        assert "| M1]" in first and "| M1]" in again
        assert "| M2]" in second
        assert projection.raw_of("M1") == "tg:100"
        assert projection.raw_of("M2") == "tg:101"
        assert projection.raw_of("U1") == "10"
        # Автор — «Имя (U1)», не числовой uid в речи.
        assert "Вася (U1)" in first
        assert "[10]" not in first

    def test_manifest_records_only_ids_labels_and_type_counts(self):
        """§4.3 п.5 + §7: в манифест — пары «метка → ID» и счётчики, без
        приватных текстов."""
        secret_text = "уникальная-приватная-фраза-про-волокна"
        projection = SpeechProjection(run_id="run-b")
        format_speech_item(
            ts=TS_ROOT, author="Вася", author_uid=10, item_id="tg:100",
            text=secret_text, projection=projection)
        format_speech_item(
            ts=TS_ROOT, author="Петя", author_uid=11, item_id="fact:7",
            text="факт графа", kind="fact", projection=projection)

        manifest = projection.manifest()
        assert manifest["representation"] == "writer"
        assert manifest["items"] == {"M1": "tg:100", "F1": "fact:7"}
        assert manifest["participants"] == {"U1": "10", "U2": "11"}
        assert manifest["counts"] == {"labels": 4, "items": 2,
                                      "participants": 2}
        # Типы служебных полей, реально вынесенных из речи (§4.5).
        assert manifest["suppressed_field_types"] == ["fact_id", "tg_id",
                                                      "user_id"]
        assert manifest["suppressed_field_counts"]["tg_id"] == 1
        assert secret_text not in repr(manifest)
        assert "волокна" not in repr(manifest)

    def test_unknown_representation_falls_back_to_writer(self):
        assert (SpeechProjection(run_id="r", representation="bogus")
                .manifest()["representation"] == "writer")

    def test_reserve_pins_chronological_numbering(self):
        """§4.3 п.3: нумерация — по хронологии прогона, даже когда рендер
        идёт от свежего к корню."""
        projection = SpeechProjection(run_id="run-c")
        projection.reserve(["tg:100", "tg:101", "tg:102"])
        newest_first = format_speech_item(
            ts=TS_ROOT + 2 * TS_STEP, author="Вася", author_uid=10,
            item_id="tg:102", text="третье", projection=projection)
        assert "| M3]" in newest_first
        assert projection.raw_of("M1") == "tg:100"


# ── §9.5 п.2: подтверждённый Reply vs семантическая связь ────────────────────

class TestRelationHonesty:
    def test_reply_and_semantic_relations_are_distinguishable(self):
        projection = SpeechProjection(run_id="run-d")
        projection.reserve(["tg:100", "tg:101", "tg:102"])
        reply_line = format_speech_item(
            ts=TS_ROOT + TS_STEP, author="Вася", author_uid=10,
            item_id="tg:101", text="ответ", projection=projection,
            relations=[SpeechRelation(RELATION_REPLY, "tg:100")])
        semantic_line = format_speech_item(
            ts=TS_ROOT + TS_STEP, author="Вася", author_uid=10,
            item_id="tg:102", text="по теме", projection=projection,
            relations=[SpeechRelation(RELATION_SEMANTIC, "tg:100")])

        assert "↳ отвечает на M1 (Telegram Reply)" in reply_line
        assert "↳ относится к теме M1 (семантическая связь, не Reply)" \
            in semantic_line
        # Семантическая связь НЕ выдаёт себя за Reply.
        assert "Telegram Reply" not in semantic_line
        assert "отвечает на" not in semantic_line

    def test_known_but_not_extracted_parent_is_missing_edge(self):
        """§8: потерянная связь — явное `missing_edge`, без выдуманного ID."""
        projection = SpeechProjection(run_id="run-e")
        line = format_speech_item(
            ts=TS_ROOT, author="Вася", author_uid=10, item_id="tg:100",
            text="ответ в пустоту", projection=projection,
            relations=[SpeechRelation(RELATION_REPLY, "tg:999")])
        assert SPEECH_RELATION_MISSING_EDGE in line
        assert "999" not in line
        assert "отвечает на" not in line

    def test_semantic_link_to_message_outside_window_is_honest(self):
        """§9.5 п.2: семантическая связь без извлечённой реплики не
        превращается ни в Reply, ни в выдуманную метку."""
        projection = SpeechProjection(run_id="run-e2")
        line = format_speech_item(
            ts=TS_ROOT, author="Вася", author_uid=10, item_id="tg:100",
            text="по теме", projection=projection,
            relations=[SpeechRelation(RELATION_SEMANTIC, "tg:555")])
        assert "относится к теме" in line
        assert "семантическая связь, не Reply" in line
        assert "вне доступного окна" in line
        assert "555" not in line

    def test_target_role_is_rendered_explicitly(self):
        """§4.3 п.4: роль проверяемого сообщения видна модели явно."""
        projection = SpeechProjection(run_id="run-e3")
        line = format_speech_item(
            ts=TS_ROOT, author="Вася", author_uid=10, item_id="tg:100",
            text="мышечные волокна растут", projection=projection,
            role="target")
        assert "]: (цель проверки) мышечные волокна растут" in line


# ── §9.2 / §8 п.4: автор цитаты — имя, не число ─────────────────────────────

class TestQuoteAuthor:
    def test_quote_author_is_named_not_numeric(self):
        projection = SpeechProjection(run_id="run-f")
        # Хронология прогона: реплика автора цитаты идёт раньше разбора.
        projection.reserve(["tg:100", "tg:101"])
        format_speech_item(
            ts=TS_ROOT, author="Вася", author_uid=10, item_id="tg:100",
            text="волокна растут как на дрожжах", projection=projection)
        line = format_speech_item(
            ts=TS_ROOT + TS_STEP, author="Петя", author_uid=11,
            item_id="tg:101", text="моя реплика", projection=projection,
            quote=SpeechQuote(text="волокна растут как на дрожжах",
                              author_name="Вася", author_uid=10))
        assert "цитата (автор: Вася (U1)): «волокна растут как на дрожжах»" \
            in line
        # Числовой uid автора цитаты в речь не попадает.
        assert "(автор: 10)" not in line

    def test_quote_author_unknown_is_honest(self):
        projection = SpeechProjection(run_id="run-g")
        line = format_speech_item(
            ts=TS_ROOT, author="Петя", author_uid=11, item_id="tg:101",
            text="реплика", projection=projection,
            quote=SpeechQuote(text="чужие слова"))
        assert "автор цитаты не определён" in line

    def test_quote_priority_and_unavailable_notes_are_preserved(self):
        """§9.5 п.1: семантика доставки цитаты не теряется при проекции."""
        projection = SpeechProjection(run_id="run-h")
        priority = format_speech_item(
            ts=TS_ROOT, author="Петя", author_uid=11, item_id="tg:101",
            text="реплика", projection=projection,
            quote=SpeechQuote(text="фрагмент", author_name="Вася",
                              author_uid=10, priority_subject=True))
        missing = format_speech_item(
            ts=TS_ROOT, author="Петя", author_uid=11, item_id="tg:102",
            text="реплика", projection=projection,
            quote=SpeechQuote(text="фрагмент", author_name="Вася",
                              author_uid=10, original_available=False))
        assert "ПРИОРИТЕТНЫЙ ПРЕДМЕТ ответа" in priority
        assert "оригинал недоступен (контекст ограничен)" in missing


# ── §9.5 п.1: абсолютное время/автор/forward/provenance ─────────────────────

class TestContextFidelity:
    def test_absolute_timestamp_is_rendered_not_ordinal(self):
        projection = SpeechProjection(run_id="run-i")
        line = format_speech_item(
            ts=TS_ROOT, author="Вася", author_uid=10, item_id="tg:100",
            text="вопрос", projection=projection)
        assert line.startswith("[30.04.2024 16:00 | ")
        # Порядковый номер массива не подменяет дату.
        assert "M1" in line and "30.04.2024" in line

    def test_forward_provenance_is_kept(self):
        projection = SpeechProjection(run_id="run-j")
        line = format_speech_item(
            ts=TS_ROOT, author="Вася", author_uid=10, item_id="tg:100",
            text="чужой текст", forward_source="Канал X",
            projection=projection)
        assert "Переслано: Канал X" in line
        assert "| M1 |" in line

    def test_missing_metadata_still_collapses_cleanly(self):
        projection = SpeechProjection(run_id="run-k")
        line = format_speech_item(text="голый текст", projection=projection)
        assert line == "голый текст"

    def test_target_marker_survives_projection(self):
        """target_marking: маркер текущей команды не теряется в проекции."""
        projection = SpeechProjection(run_id="run-l")
        line = format_speech_item(
            ts=TS_ROOT, author="Вася", author_uid=10, item_id="tg:100",
            text="фактчек", is_target=True, projection=projection)
        assert TARGET_MARKER_CORE in line
        assert "| M1]" in line
        raw = format_context_item(
            ts=TS_ROOT, author="Вася", item_id="tg:100", text="фактчек",
            is_target=True)
        assert raw.endswith(TARGET_MARKER)


# ── §4.3 п.3: метка — адресная разметка, не часть реплики ───────────────────

class TestLabelNeverSplicedIntoSpeechText:
    def test_label_lives_in_header_only(self):
        projection = SpeechProjection(run_id="run-m")
        body = "в теле реплики нет меток"
        line = format_speech_item(
            ts=TS_ROOT, author="Вася", author_uid=10, item_id="tg:100",
            text=body, projection=projection)
        header, _, text = line.partition("]: ")
        assert "M1" in header
        assert text == body
        # Метка не продублирована в тексте участника.
        assert text.count("M1") == 0

    def test_quoted_text_is_verbatim_and_labels_stay_outside(self):
        projection = SpeechProjection(run_id="run-n")
        quote_text = "он писал 1194297 про отверстия"
        line = format_speech_item(
            ts=TS_ROOT, author="Петя", author_uid=11, item_id="tg:101",
            text="разбор цитаты", projection=projection,
            quote=SpeechQuote(text=quote_text, author_name="Вася",
                              author_uid=10))
        # Пользовательское число сохраняется как содержание (§9.2/сц.62).
        assert f"«{quote_text}»" in line
        guillemet = line.split("«", 1)[1].split("»", 1)[0]
        assert "M" not in guillemet and "U1" not in guillemet


# ── R1/§5.4: машинная сторона не меняется ───────────────────────────────────

class TestRawMachineFormUntouched:
    def test_resolve_item_id_unchanged(self):
        assert resolve_item_id(tg_message_id=100) == "tg:100"
        assert resolve_item_id(message_id=9) == "msg:9"
        assert resolve_item_id(fact_id=4) == "fact:4"
        assert resolve_item_id() == ""

    def test_format_context_item_keeps_typed_refs_and_numeric_uid(self):
        raw = format_context_item(
            ts=TS_ROOT, author="вася [10]", item_id="tg:100", text="привет")
        assert raw == "[30.04.2024 16:00 | вася [10] | tg:100]: привет"

    def test_chain_line_stays_raw_for_machine_consumers(self):
        """`format_chain_line` — машинная сторона (direct-дедуп по `tg:`,
        attribution, планировщик): остаётся сырым (R1/§4.2 п.1)."""
        item = thread_chain.ChainItem(
            uid=10, name="вася", text="привет", is_bot=False,
            ts=TS_ROOT, item_id="tg:100", reply_to_item_id="tg:99")
        raw_line = thread_chain.format_chain_line(item)
        assert "tg:100" in raw_line and "[10]" in raw_line

    def test_reply_chains_default_surface_is_speech(self):
        """Главная речевая поверхность фактчека: по умолчанию — метки, без
        `tg:` и без числового uid автора цитаты (§4.3, §7.2)."""
        item = thread_chain.ChainItem(
            uid=10, name="вася", text="привет", is_bot=False,
            ts=TS_ROOT, item_id="tg:100")
        block = thread_chain.render_reply_chains([item])
        assert "<reply_chains" in block
        assert "| M1]" in block and "вася (U1)" in block
        assert "tg:100" not in block and "[10]" not in block

    def test_speech_projection_does_not_leak_into_default_paths(self):
        """Проекция применяется только при явной передаче `projection`."""
        projection = SpeechProjection(run_id="run-o")
        implicit = format_speech_item(
            ts=TS_ROOT, author="Вася", author_uid=10, item_id="tg:100",
            text="привет")
        assert implicit == format_context_item(
            ts=TS_ROOT, author="Вася", item_id="tg:100", text="привет")
        assert projection.manifest()["counts"]["labels"] == 0


# ── §6.2: единственный горячий рубильник ────────────────────────────────────

class TestSpeechProjectionFlag:
    def test_hot_key_drives_the_seam(self, hot_cache):
        hot_cache({"flags.context_speech_projection": False})
        assert speech_projection_enabled() is False
        hot_cache({"flags.context_speech_projection": True})
        assert speech_projection_enabled() is True

    def test_settings_default_is_on(self):
        assert getattr(Settings, "CONTEXT_SPEECH_PROJECTION_ENABLED") is True
        assert speech_projection_enabled() is True

    def test_switch_follows_kill_switch_convention(self):
        """§6.2 + конвенция репозитория: рубильник — ClassVar (Δ каталога = 0),
        прецедент SUMMARY_WRITER_SOURCE_INPUT_ENABLED. Каталог параметров не
        растёт, откат живёт в hot-ключе."""
        import dataclasses
        fields = {f.name for f in dataclasses.fields(Settings)}
        assert "CONTEXT_SPEECH_PROJECTION_ENABLED" not in fields
        from services import param_catalog as pc
        pg_keys = {spec.pg_key for spec in pc.REGISTRY.values()}
        assert "flags.context_speech_projection" not in pg_keys

    def test_env_off_restores_raw_canon(self, monkeypatch):
        """Вторая ветка отката: env-дефолт OFF (рестарт) ведёт себя так же."""
        monkeypatch.setattr(Settings, "CONTEXT_SPEECH_PROJECTION_ENABLED",
                            False)
        projection = SpeechProjection(run_id="run-env")
        line = format_speech_item(
            ts=TS_ROOT, author="Вася", author_uid=10, item_id="tg:100",
            text="вопрос", projection=projection)
        assert line == format_context_item(
            ts=TS_ROOT, author="Вася", item_id="tg:100", text="вопрос")
        assert projection.manifest()["counts"]["labels"] == 0

    def test_flag_off_restores_raw_canon_byte_for_byte(self, hot_cache):
        projection = SpeechProjection(run_id="run-p")
        speech = format_speech_item(
            ts=TS_ROOT, author="Вася", author_uid=10, item_id="tg:100",
            text="вопрос", projection=projection,
            relations=[SpeechRelation(RELATION_REPLY, "tg:100")])
        assert "M1" in speech

        # Откат — горячий ключ (PG), без рестарта (§6.2).
        hot_cache({"flags.context_speech_projection": False})
        rolled_back = format_speech_item(
            ts=TS_ROOT, author="Вася", author_uid=10, item_id="tg:100",
            text="вопрос", projection=projection,
            relations=[SpeechRelation(RELATION_REPLY, "tg:100")])
        assert rolled_back == format_context_item(
            ts=TS_ROOT, author="Вася", item_id="tg:100", text="вопрос")

    def test_flag_off_restores_raw_chain_block(self, hot_cache):
        projection = SpeechProjection(run_id="run-q")
        items = [thread_chain.ChainItem(
            uid=10, name="вася", text="привет", is_bot=False,
            ts=TS_ROOT, item_id="tg:100")]
        speech = thread_chain.render_reply_chains(
            items, projection=projection)
        assert "| M1]" in speech

        hot_cache({"flags.context_speech_projection": False})
        rolled_back = thread_chain.render_reply_chains(items)
        assert "tg:100" in rolled_back and "[10]" in rolled_back
        assert "| M" not in rolled_back


# ── E10/§13 сц.97–98: личности не сливаются ────────────────────────────────

class TestIdentitySeparation:
    def test_same_display_name_gets_distinct_labels(self):
        projection = SpeechProjection(run_id="run-r")
        first = projection.person_label(10, "Вася")
        second = projection.person_label(20, "Вася")
        assert first == "Вася (U1)"
        assert second == "Вася (U2)"
        assert projection.raw_of("U1") == "10"
        assert projection.raw_of("U2") == "20"

    def test_unknown_identity_gets_no_shared_label(self):
        """Нет user id → метки нет: слияние разных людей запрещено."""
        projection = SpeechProjection(run_id="run-s")
        assert projection.person_label(None, "Вася") == "Вася"
        assert projection.person_label(None, "Вася") == "Вася"
        assert projection.manifest()["participants"] == {}

    def test_bot_turn_is_not_labelled_as_person(self):
        projection = SpeechProjection(run_id="run-t")
        assert projection.person_label(None, "бот", is_bot=True) == "бот"
        assert projection.manifest()["participants"] == {}


# ── F13/§4.2 п.2: медиа-маркер в речевом виде ───────────────────────────────

class TestMediaMarkerSpeechForm:
    def test_raw_marker_unchanged(self):
        assert media_marker("video", "tg:123") == "[медиа: video tg:123]"
        assert media_marker("video", "msg:77") == "[медиа: video msg:77]"

    def test_speech_marker_uses_run_label(self):
        projection = SpeechProjection(run_id="run-u")
        marker = media_marker("video", "tg:123", projection=projection)
        assert marker == "[медиа: video M1]"
        assert projection.raw_of("M1") == "tg:123"
        # Контракт маркера для потребителя принимает метку как ref.
        assert MEDIA_MARKER_RE.match(marker)
        assert MEDIA_MARKER_RE.match("[медиа: video tg:123]")

    def test_unaddressable_node_drops_ref_in_speech_form(self):
        projection = SpeechProjection(run_id="run-v")
        assert media_marker("video", None,
                            projection=projection) == "[медиа: video]"

    def test_explicit_label_is_sanitized(self):
        assert media_marker("video", None,
                            label="M7") == "[медиа: video M7]"
        # Мусор вместо метки не вставляется в маркер: реф просто опускается.
        assert media_marker("video", None,
                            label="tg:1] зло") == "[медиа: video]"


# ── §4.2 п.2 + §4.3 п.3/п.4: полный речевой рендер цепочки ─────────────────

class TestSpeechChainRendering:
    @pytest.mark.asyncio
    async def test_chain_preserves_edges_authors_time_and_media(self):
        corner = 1_714_492_860
        messages = {
            100: _row(text="про волокна", tg_message_id=100, id=900,
                      user_id=10, author_name="Вася", timestamp=corner,
                      reply_to_id=None),
            101: _row(text="", tg_message_id=101, id=901, user_id=10,
                      author_name="Вася", timestamp=corner + 60,
                      reply_to_id=100, media_type="video"),
            102: _row(text="а при чём тут мышцы?", tg_message_id=102, id=902,
                      user_id=11, author_name="Хан", timestamp=corner + 120,
                      reply_to_id=101),
        }
        db = _FakeChainDB(messages)
        chain = await thread_chain.collect_thread_chain(db, CHAT_ID, 102, 5)
        projection = SpeechProjection(run_id="run-w")
        block = thread_chain.render_reply_chains(
            chain, projection=projection)

        # Хронология: корень → свежее, метки по порядку.
        assert block.index("| M1]") < block.index("| M2]") < block.index("| M3]")
        assert projection.raw_of("M1") == "tg:100"
        assert projection.raw_of("M3") == "tg:102"
        # Reply-край напечатан явно и только там, где он реально есть.
        assert "↳ отвечает на M1 (Telegram Reply)" in block
        assert "↳ отвечает на M2 (Telegram Reply)" in block
        # Медиа-строка несёт метку, а не внутренний ref.
        assert "[медиа: video M2]" in block
        assert "tg:101" not in block
        assert "tg:100" not in block
        # Автор различается меткой, имена разные.
        assert "Вася (U1)" in block and "Хан (U2)" in block
        # Абсолютное время сохранено.
        assert "30.04.2024 16:01" in block

    @pytest.mark.asyncio
    async def test_chain_reads_quote_author_name_from_additive_field(self):
        messages = {
            100: _row(text="волокна растут", tg_message_id=100, id=900,
                      user_id=10, author_name="Вася", timestamp=TS_ROOT),
            101: _row(text="разбор", tg_message_id=101, id=901, user_id=11,
                      author_name="Хан", timestamp=TS_ROOT + 60,
                      reply_to_id=100, quote_text="волокна растут",
                      quote_author_id=10),
        }
        db = _FakeChainDB(messages)
        chain = await thread_chain.collect_thread_chain(
            db, CHAT_ID, 101, 5,
            quote_author_resolver=lambda uid: "Вася" if uid == 10 else "")
        projection = SpeechProjection(run_id="run-x")
        block = thread_chain.render_reply_chains(
            chain, projection=projection)
        assert "цитата (автор: Вася (U1)): «волокна растут»" in block
        assert "(автор: 10)" not in block

    @pytest.mark.asyncio
    async def test_chain_without_name_resolver_keeps_identity_label(self):
        """Без резолвера имени личность всё равно различима меткой `U1`
        (обратная карта run'а), а не числовым uid (§9.2)."""
        messages = {
            100: _row(text="волокна растут", tg_message_id=100, id=900),
            101: _row(text="разбор", tg_message_id=101, id=901,
                      user_id=11, author_name="Хан",
                      timestamp=TS_ROOT + 60, reply_to_id=100,
                      quote_text="волокна растут", quote_author_id=10),
        }
        db = _FakeChainDB(messages)
        chain = await thread_chain.collect_thread_chain(db, CHAT_ID, 101, 5)
        projection = SpeechProjection(run_id="run-y")
        block = thread_chain.render_reply_chains(
            chain, projection=projection)
        assert "автор цитаты не определён" not in block
        assert "цитата (автор: U1)" in block
        assert "(автор: 10)" not in block
        # Метка ведёт на реального человека (Вася, user 10).
        assert projection.raw_of("U1") == "10"

    @pytest.mark.asyncio
    async def test_empty_chain_renders_empty(self):
        assert thread_chain.render_reply_chains([]) == ""


# ── §9.4: наблюдаемость — представление + типы, без текстов ─────────────────

class TestSpeechProjectionObservability:
    def test_event_records_representation_and_field_types_only(
            self, monkeypatch):
        captured = []

        def _capture(event_name, **fields):
            captured.append((event_name, fields))
            return None

        monkeypatch.setattr(mca_events, "emit_mca_event", _capture)
        projection = SpeechProjection(run_id="run-ev",
                                      representation=REPRESENTATION_INTERNAL)
        projection.message_label("tg:100")
        projection.person_label(10, "Вася")
        cc.emit_speech_projection_event(projection, chat_id=CHAT_ID)

        assert len(captured) == 1
        name, fields = captured[0]
        assert name == "speech_projection"
        assert fields["status"] == REPRESENTATION_INTERNAL
        assert fields["component"] == "context"
        assert fields["entity_ids"]["items"] == {"M1": "tg:100"}
        assert fields["entity_ids"]["participants"] == {"U1": "10"}
        assert fields["entity_ids"]["suppressed_field_types"] == [
            "tg_id", "user_id"]
        assert "Вася" not in repr(fields)
