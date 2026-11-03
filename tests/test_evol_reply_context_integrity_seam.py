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
from services.chat_context import (
    _REPLY_CHAINS_MAX_CHARS,
    _truncate_reply_chains,
)
from services.target_marking import TARGET_MARKER_CORE, TARGET_MARKER

CHAT_ID = -1007001
# Время проверяется абсолютное: 30.04.2024 16:00 UTC.
TS_ROOT = 1_714_492_800
TS_STEP = 60


def reply_chains_cap() -> int:
    """Действующий кап под-блока цепочек (не растёт в этой правке)."""
    return _REPLY_CHAINS_MAX_CHARS


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
    """Минимальный ConfigCache-совместимый стаб для hot-ключа.

    Держит ССЫЛКУ на переданный dict: тест «горячего» переключения меняет
    значение в живом кэше, не переустанавливая объект."""

    def __init__(self, values):
        self.values = values

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

        assert "↳ Reply M1" in reply_line
        assert "↳ по теме M1 (не Reply)" in semantic_line
        # Семантическая связь НЕ выдаёт себя за Reply.
        assert "Reply M1" not in semantic_line
        assert "↳ Reply" not in semantic_line

    def test_known_but_not_extracted_parent_is_missing_edge(self):
        """§8: потерянная связь — явное `missing_edge`, без выдуманного ID."""
        projection = SpeechProjection(run_id="run-e")
        line = format_speech_item(
            ts=TS_ROOT, author="Вася", author_uid=10, item_id="tg:100",
            text="ответ в пустоту", projection=projection,
            relations=[SpeechRelation(RELATION_REPLY, "tg:999")])
        assert SPEECH_RELATION_MISSING_EDGE in line
        assert "999" not in line
        assert "↳ Reply" not in line

    def test_semantic_link_to_message_outside_window_is_honest(self):
        """§9.5 п.2: семантическая связь без извлечённой реплики не
        превращается ни в Reply, ни в выдуманную метку."""
        projection = SpeechProjection(run_id="run-e2")
        line = format_speech_item(
            ts=TS_ROOT, author="Вася", author_uid=10, item_id="tg:100",
            text="по теме", projection=projection,
            relations=[SpeechRelation(RELATION_SEMANTIC, "tg:555")])
        assert "по теме" in line
        assert "не Reply" in line
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
        растёт; следствие (B3 ревью) — ключ не имеет админ-тумблера, поэтому
        `param_catalog` его не знает, а `PUT /api/config` его отвергает."""
        import dataclasses
        fields = {f.name for f in dataclasses.fields(Settings)}
        assert "CONTEXT_SPEECH_PROJECTION_ENABLED" not in fields
        from services import param_catalog as pc
        pg_keys = {spec.pg_key for spec in pc.REGISTRY.values()}
        assert "flags.context_speech_projection" not in pg_keys
        assert pc.get_by_pg_key("flags.context_speech_projection") is None

    def test_stored_string_values_are_typed(self):
        """B3 ревью: jsonb-строка из bot_settings не должна читаться как
        `bool("false") is True` — OFF-токены распознаются явно."""
        from services.canonical_context import coerce_switch_flag
        for off_value in (False, 0, "false", "False", "0", "off", "OFF",
                          "no", "disabled", " false "):
            assert coerce_switch_flag(off_value) is False, off_value
        for on_value in (True, 1, "true", "1", "on", "yes", "enabled"):
            assert coerce_switch_flag(on_value) is True, on_value
        # «Не задано» и неизвестный мусор не выключают фичу молча — дефолт.
        for unset in (None, "", "  "):
            assert coerce_switch_flag(unset) is True, unset
            assert coerce_switch_flag(unset, default=False) is False
        assert coerce_switch_flag("maybe", default=True) is True
        assert coerce_switch_flag("maybe", default=False) is False

    def test_stored_string_false_switches_the_seam_off(self, hot_cache):
        hot_cache({"flags.context_speech_projection": "false"})
        assert speech_projection_enabled() is False
        projection = SpeechProjection(run_id="run-str")
        line = format_speech_item(
            ts=TS_ROOT, author="Вася", author_uid=10, item_id="tg:100",
            text="вопрос", projection=projection)
        assert line == format_context_item(
            ts=TS_ROOT, author="Вася", item_id="tg:100", text="вопрос")

    def test_flip_applies_without_restart_on_next_render(self, hot_cache):
        """Рубильник читается на КАЖДОМ рендере (без кэша в шве): изменение
        живого ConfigCache действует со следующего payload, рестарт не нужен."""
        live = {"flags.context_speech_projection": True}
        hot_cache(live)                       # один и тот же живой кэш
        projection = SpeechProjection(run_id="run-live")
        assert "| M1]" in format_speech_item(
            ts=TS_ROOT, author="Вася", author_uid=10, item_id="tg:100",
            text="вопрос", projection=projection)

        live["flags.context_speech_projection"] = False   # flip на месте
        assert speech_projection_enabled() is False
        assert format_speech_item(
            ts=TS_ROOT, author="Вася", author_uid=10, item_id="tg:100",
            text="вопрос", projection=projection) == format_context_item(
            ts=TS_ROOT, author="Вася", item_id="tg:100", text="вопрос")

        live["flags.context_speech_projection"] = True    # и обратно
        assert "| M1]" in format_speech_item(
            ts=TS_ROOT, author="Вася", author_uid=10, item_id="tg:100",
            text="вопрос", projection=projection)

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
        """Бот не получает `U`-метку и не попадает в карту участников, но
        РОЛЬ в речевой форме сохраняется (§5.4 «и самого бота», сц.116)."""
        projection = SpeechProjection(run_id="run-t")
        assert projection.person_label(None, "бот", is_bot=True) == "бот"
        assert projection.person_label(None, "Adminbot",
                                       is_bot=True) == "Adminbot (бот)"
        assert projection.person_label(None, "", is_bot=True) == "бот"
        assert projection.manifest()["participants"] == {}


class TestBotRolePreserved:
    """B2 ревью: прошлый ответ бота нельзя перепутать с репликой человека.

    Сырой вид помечал бот-хода ``[bot]``; речевая проекция этот маркер
    теряла (осталось «Adminbot | M6»), и ход бота становился неотличим от
    участника без user id (§5.4, §13 сц.116).
    """

    def test_speech_line_of_bot_turn_carries_role_marker(self):
        projection = SpeechProjection(run_id="run-bot")
        line = format_speech_item(
            ts=None, author="Adminbot", item_id="tg:300",
            text="мой прошлый ответ", projection=projection, is_bot=True)
        assert "Adminbot (бот)" in line
        assert "[bot]" not in line           # сырой маркер не дублируется
        assert projection.manifest()["participants"] == {}

    def test_bot_turn_differs_from_person_without_user_id(self):
        projection = SpeechProjection(run_id="run-bot2")
        bot = format_speech_item(
            ts=None, author="Adminbot", item_id="tg:300", text="ответ",
            projection=projection, is_bot=True)
        human = format_speech_item(
            ts=TS_ROOT, author="Вася", item_id="tg:301", text="ответ",
            projection=projection)
        assert "(бот)" in bot
        assert "(бот)" not in human
        assert "Вася" in human

    @pytest.mark.asyncio
    async def test_bot_turn_in_chain_keeps_role_in_speech_form(self):
        # Ход бота: tg:100 нет в smart_messages, но есть bot_reply на него.
        messages = {
            101: _row(text="а это точно так?", tg_message_id=101, id=901,
                      user_id=10, author_name="Вася", timestamp=TS_ROOT,
                      reply_to_id=100),
        }
        db = _FakeChainDB(messages, bot_replies={100: "да, точнее некуда"})
        chain = await thread_chain.collect_thread_chain(db, CHAT_ID, 101, 5)
        assert any(item.is_bot for item in chain)
        projection = SpeechProjection(run_id="run-bot3")
        block = thread_chain.render_reply_chains(
            chain, projection=projection)
        # Явная роль бота в речевой форме; сырой `[bot]` не протекает.
        assert "бот" in block
        assert "[bot]" not in block
        bot_line = [ln for ln in block.split("\n") if "точнее некуда" in ln][0]
        assert "бот" in bot_line.split("]: ")[0]
        # Метка роли не выдаётся как участник-человек.
        assert projection.manifest()["participants"] == {"U1": "10"}

    def test_raw_machine_surface_keeps_bot_marker(self):
        """Машинная сторона не меняется: `format_chain_line` по-прежнему
        отдаёт ``[bot]`` (direct-дедуп/attribution)."""
        item = thread_chain.ChainItem(
            uid=None, name="Adminbot", text="ответ", is_bot=True,
            ts=None, item_id="tg:300")
        assert "[bot]" in thread_chain.format_chain_line(item)


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
        assert "↳ Reply M1" in block
        assert "↳ Reply M2" in block
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
    async def test_chain_without_name_resolver_says_author_unknown(self):
        """Без резолвера имени голой метки в речи НЕТ (§9.2, сц.100/115).

        Адресная метка человека не называет («автор: U1» — не ответ на
        вопрос «кто это сказал»), поэтому речевая сторона честно объявляет
        неопределённость. Обратная карта при этом полная: метка автора
        зарегистрирована в проекции прогона (машинный слой знает `U1→10`).
        Ревью волны потребителей, F1: продовая проводка обязана передавать
        резолвер, иначе это и есть прод-поведение."""
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
        assert "цитата (автор: автор цитаты не определён)" in block
        # Голой адресной метки на месте автора нет (её не озвучивают).
        assert "цитата (автор: U1)" not in block
        assert "(автор: 10)" not in block
        # Метка автора всё равно зарегистрирована (машинный слой → U1 = 10).
        assert projection.raw_of("U1") == "10"

    @pytest.mark.asyncio
    async def test_empty_chain_renders_empty(self):
        assert thread_chain.render_reply_chains([]) == ""


# ── B1: кап цепочки не теряет корень молча ─────────────────────────────────

class TestChainCapKeepsRootAndSaysWhatItCut:
    """B1 ревью: речевая проекция удлиняла под-блок на 10–28 %, и на узком
    маршруте (``_REPLY_CHAINS_MAX_CHARS`` = 1200, keep-end) молча выпадал
    КОРЕНЬ цепочки. Требование: §5.1/§5.2 («родитель и критическая атрибуция
    не должны молча исчезнуть»), R7 («бюджет не растёт»)."""

    TEXT = ["разбор про волокна и 1194297", "а версия 2.58.153 от 30.04?",
            "не согласен, это про синтез белка", "он писал иначе, ссылка выше",
            "проверь, пожалуйста, ещё раз"]

    def _chain(self, turns):
        items = [thread_chain.ChainItem(
            uid=10 + (i % 3),
            name=("Марина К.", "Вася", "Хан")[i % 3],
            text=self.TEXT[i % len(self.TEXT)], is_bot=False,
            ts=TS_ROOT + 60 * i, item_id=f"tg:{700 + i}",
            reply_to_item_id=(f"tg:{700 + i - 1}" if i else ""))
            for i in range(turns)]
        return list(reversed(items))          # как collect_thread_chain

    def _render(self, turns):
        projection = SpeechProjection(run_id=f"run-cap-{turns}")
        return thread_chain.render_reply_chains(
            self._chain(turns), projection=projection)

    def test_cap_itself_did_not_grow(self):
        """«Новых бюджетов не вводить»: кап под-блока остался 1200, а флаг
        живёт отдельно от него (никаких дополнительных лимитов не добавлено)."""
        assert reply_chains_cap() == 1200
        from config.settings import settings
        assert not hasattr(settings, "CONTEXT_SPEECH_PROJECTION_MAX_CHARS")

    def test_speech_block_fits_cap_for_normal_chain(self):
        """Проверка ревью: 12 ходов (глубина 20). Раньше речевая форма
        выходила за кап и теряла корень — теперь укладывается и корень на
        месте."""
        speech = self._render(12)
        assert len(speech) <= reply_chains_cap(), (len(speech), speech)
        truncated = _truncate_reply_chains(speech, reply_chains_cap())
        assert truncated == speech                 # ничего не потеряно
        kept = [ln for ln in truncated.split("\n") if ln.startswith("[")]
        assert len(kept) == 12
        # Корень цепочки (самый старый ход) на месте, метка M1 не выброшена.
        assert kept[0].startswith("[" + "30.04.2024 16:00")
        assert "| M1]" in kept[0]
        assert "часть цепочки не показана" not in truncated

    def test_size_delta_of_speech_form_is_small(self):
        """R7: речевая форма не удваивает под-блок. Компактная клауза
        ``↳ Reply M2`` вместо длинного пояснения держит дельту в пределах
        ~10 % (было 10–28 % при длинной клаузе)."""
        from config.settings import Settings as _Settings
        chain = self._chain(12)
        saved = _Settings.CONTEXT_SPEECH_PROJECTION_ENABLED
        _Settings.CONTEXT_SPEECH_PROJECTION_ENABLED = False
        try:
            raw = thread_chain.render_reply_chains(chain)
        finally:
            _Settings.CONTEXT_SPEECH_PROJECTION_ENABLED = saved
        speech = self._render(12)
        ratio = len(speech) / len(raw)
        # Ответы + явные отношения: небольшой рост допустим, скачок — нет.
        assert ratio <= 1.10, (len(raw), len(speech), ratio)
        assert "↳ Reply M2" in speech

    def test_cap_really_cutting_prints_explicit_notice(self):
        """Когда кап ДЕЙСТВИТЕЛЬНО режет, потеря количества ходов объявляется
        явно, а не молчит (§5.1/§5.2)."""
        speech = self._render(16)                 # заведомо длиннее капа
        cap = reply_chains_cap()
        truncated = _truncate_reply_chains(speech, cap)
        assert len(truncated) <= cap
        assert truncated.endswith("</reply_chains>")
        notice = [ln for ln in truncated.split("\n")
                  if "часть цепочки не показана" in ln]
        assert len(notice) == 1
        kept = [ln for ln in truncated.split("\n")
                if ln.startswith("[") and "]: " in ln]
        dropped = len([ln for ln in speech.split("\n")
                       if ln.startswith("[") and "]: " in ln]) - len(kept)
        assert dropped > 0
        assert notice[0].strip() == f"…часть цепочки не показана ({dropped})"

    def test_notice_itself_stays_within_budget(self):
        """Пометка не выводит блок из бюджета: она сама укладывается в лимит
        (при нехватке вытесняется ещё один старый ход)."""
        speech = self._render(20)
        for cap in (300, 420, 600, 1200):
            truncated = _truncate_reply_chains(speech, cap)
            assert len(truncated) <= cap, (cap, len(truncated) - cap)

    def test_default_depth_chain_has_no_notice(self):
        """Дефолтная глубина 6–8 и короткие реплики: кап не срабатывает и
        никакой пометки нет (поведение прежнее)."""
        short = thread_chain.render_reply_chains(
            [thread_chain.ChainItem(
                uid=10, name="Вася", text="да", is_bot=False,
                ts=TS_ROOT + i, item_id=f"tg:{i}") for i in range(6)],
            projection=SpeechProjection(run_id="run-short"))
        truncated = _truncate_reply_chains(short, reply_chains_cap())
        assert truncated == short
        assert "часть цепочки не показана" not in truncated


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

    def test_event_carries_chat_and_run_correlation(self, monkeypatch):
        """R1 ревью: событие привязано к реальному чату и прогону, а не
        висит без корреляции (§4.5 «run-манифест», §7 «коррелируемые
        события»). Текстов в событии нет."""
        captured = []

        def _capture(event_name, **fields):
            captured.append((event_name, fields))
            return None

        monkeypatch.setattr(mca_events, "emit_mca_event", _capture)
        chain = [thread_chain.ChainItem(
            uid=10, name="Вася", text="секретная фраза про волокна",
            is_bot=False, ts=TS_ROOT, item_id="tg:700")]
        thread_chain.render_reply_chains(
            chain, 700, chat_id=CHAT_ID, run_id="run-corr")

        assert len(captured) == 1
        name, fields = captured[0]
        assert name == "speech_projection"
        assert fields["chat_id"] == CHAT_ID
        assert fields["message_id"] == 700
        assert fields["trace_id"] == "run-corr"
        assert fields["entity_ids"]["run_id"] == "run-corr"
        # Манифест прогона и обратная карта видны в событии.
        assert fields["entity_ids"]["items"] == {"M1": "tg:700"}
        assert "волокна" not in repr(fields)

    def test_event_gets_run_id_from_chat_and_anchor_when_not_passed(
            self, monkeypatch):
        """Без явного run_id событие всё равно коррелируется: chat + якорь."""
        captured = []

        def _capture(event_name, **fields):
            captured.append((event_name, fields))
            return None

        monkeypatch.setattr(mca_events, "emit_mca_event", _capture)
        chain = [thread_chain.ChainItem(
            uid=10, name="Вася", text="вопрос", is_bot=False,
            ts=TS_ROOT, item_id="tg:700")]
        thread_chain.render_reply_chains(chain, 700, chat_id=CHAT_ID)

        _name, fields = captured[0]
        assert fields["chat_id"] == CHAT_ID
        assert fields["message_id"] == 700
        assert fields["trace_id"] == f"chat:{CHAT_ID}:msg:700"
