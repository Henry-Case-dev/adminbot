"""UR-17 / UR-17.3 / UR-ACC-D6 — replay реального исторического диалога.

Источник — прод-БД (read-only) на выложенном 2.58.257: `smart_messages` +
`mca_bot_outputs`, окно 04.11.2026 07:45–08:15 MSK. Фикстура санитизирована
(uid/имена → токены, тексты → перефразы с сохранением речевого акта), но
СТРУКТУРА настоящая: порядок строк, reply-рёбра, автор адресата.

Проверяется детерминированная часть контракта:
  * диалог проходится ЦЕЛИКОМ как хронологическая серия (UR-17/ACC-D6);
  * каждое reply-ребро разрешается и ведёт на автора, которому адресован ответ
    (UR-17.3: чужой ответ не уходит другому участнику);
  * нет self-reply и обращений «самому себе»;
  * межходовый рефрен НЕ объявляется проверенным там, где в окне всего один
    ход бота (UR-17.6): фикстура обязана честно отмечать наблюдаемость.

Модельно-зависимые части (игра/утверждение/память по «Рофлославу», атрибуция
после коррекции, повтор шутки между ходами бота) в истории ОТСУТСТВУЮТ — это
live-наблюдение, а не предмет этого детерминированного теста (см.
`source.observability` фикстуры).

TEST-LIFECYCLE: CONTRACT owner=UNIFIED-REPLY/UR-17
"""
import datetime
import json
import os
from pathlib import Path

import pytest

# UR_HISTORICAL_DIALOG — только для мутационного RED-прогона (копия фикстуры).
FIXTURE = Path(os.environ.get("UR_HISTORICAL_DIALOG") or (
    Path(__file__).resolve().parent
    / "fixtures" / "unified_reply" / "historical_dialog_2026_11_04.json"))

ALLOWED_INTENTS = {
    "agreement", "forecast", "aphorism", "thesis", "claim_about_third_party",
    "counter", "question", "irony", "media", "link", "short_reaction",
    "joke", "media_with_caption", "playful_summary",
}
ALLOWED_KINDS = {"text", "photo", "video", "initiative_reply"}


@pytest.fixture(scope="module")
def dialog():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    by_id = {m["id"]: m for m in data["messages"]}
    return data, by_id


def _utc(value: str) -> datetime.datetime:
    return datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=datetime.timezone.utc)


def test_fixture_provenance_is_complete_and_not_invented(dialog):
    """Серия пройдена целиком: ничего не выброшено и ничего не дописано."""
    data, by_id = dialog
    messages = data["messages"]
    source = data["source"]

    # Сплошная нумерация без пропусков — «диалог прочитан целиком».
    assert [m["seq"] for m in messages] == list(range(1, len(messages) + 1))
    assert len(by_id) == len(messages), "id сообщений обязаны быть уникальны"

    bot_turns = [m for m in messages if m["uid"] == "ubot"]
    human_turns = [m for m in messages if m["uid"] != "ubot"]
    # Числа провенанса совпадают с фактическим составом фикстуры: 23 реальных
    # сообщения + 1 реальный ответ бота. Подмена/дописывание это ломает.
    assert source["real_message_count"] == len(human_turns) == 23
    assert source["real_bot_output_count"] == len(bot_turns) == 1

    for m in messages:
        assert m["kind"] in ALLOWED_KINDS, m["id"]
        assert m["intent"] in ALLOWED_INTENTS, m["id"]
        assert m["uid"] in data["uids"], m["id"]
        if m["kind"] in ("photo", "video") and not m["text"]:
            assert m["intent"] == "media", m["id"]


def test_series_is_chronological(dialog):
    """Настоящий порядок строк сохранён: время строго не убывает."""
    data, _ = dialog
    stamps = [_utc(m["utc"]) for m in data["messages"]]
    assert stamps == sorted(stamps), "хронология серии нарушена"
    # Окно совпадает с заявленным в провенансе (04.11 07:45–08:15 MSK).
    lo, hi = (_utc(x) for x in data["source"]["window_utc"])
    assert lo <= stamps[0] and stamps[-1] <= hi


def test_reply_edges_resolve_to_the_real_target_author(dialog):
    """Reply-рёбра не выдуманы: цель существует и её автор = автор адресата."""
    data, by_id = dialog
    edges = {}
    for m in data["messages"]:
        target = m["reply_to"]
        if target is None:
            continue
        edges[m["id"]] = target
        if target in by_id:
            parent = by_id[target]
            assert parent["seq"] < m["seq"], (
                "%s отвечает на более позднее сообщение %s" % (m["id"], target))
            assert m["reply_author_uid"] == parent["uid"], (
                "%s: адресат reply не совпадает с автором цели" % m["id"])
            assert m["addressed_to_uid"] == parent["uid"]
        else:
            ext = data["ext_targets"].get(target)
            assert ext is not None, "%s: неизвестная цель %s" % (m["id"], target)
            assert m["reply_author_uid"] == ext["author_uid"]
            assert m["addressed_to_uid"] == ext["author_uid"]

    # Настоящий набор рёбер (проверен по прод-данным): 8 внутренних + 5 на
    # сообщения до окна. Любая «дорисовка» адресации меняет этот набор.
    assert edges == {
        "m1": "ext1", "m2": "ext1", "m3": "ext1", "m5": "ext2",
        "m6": "ext1", "m7": "m5", "m10": "m7", "m12": "m9",
        "m13": "m9", "m14": "m13", "m15": "m14", "m18": "m17",
        "m19": "m14",
    }
    assert len([t for t in edges.values() if t in by_id]) == 8
    assert len([t for t in edges.values() if t.startswith("ext")]) == 5


def test_reply_never_targets_the_sender_himself(dialog):
    """UR-17.3: ответ не приписывается самому отвечающему."""
    data, _ = dialog
    for m in data["messages"]:
        if m["reply_to"] is None:
            continue
        assert m["addressed_to_uid"] != m["uid"], (
            "%s: ответ адресован собственному автору" % m["id"])


def test_bot_turn_addresses_the_thread_not_a_random_participant(dialog):
    """Инициативный ответ бота не выдаёт себя за ответ конкретному человеку."""
    data, _ = dialog
    bot = [m for m in data["messages"] if m["uid"] == "ubot"]
    assert len(bot) == 1
    turn = bot[0]
    assert turn["kind"] == "initiative_reply"
    assert turn["reply_to"] is None and turn["addressed_to_uid"] is None
    # Эхо чужой шутки помечено и указывает на реальное сообщение участника.
    by_id = {m["id"]: m for m in data["messages"]}
    echo_of = turn["echo_of"]
    assert echo_of and all(t in by_id for t in echo_of)
    for target in echo_of:
        assert by_id[target]["uid"] != "ubot", "эхо обязано ссылаться на человека"


def test_refrain_is_not_claimed_where_it_is_unobservable(dialog):
    """UR-17.6: при одном ходе бота повтор шутки не «доказан», а помечен live."""
    data, _ = dialog
    bot_turns = [m for m in data["messages"] if m["uid"] == "ubot"]
    obs = data["observability"]
    assert obs["bot_turns_in_window"] == len(bot_turns)
    if len(bot_turns) < 2:
        assert obs["refrain_observable"] is False
        assert obs["refrain_reason"], "причина обязана быть названа"
    else:      # pragma: no cover - в этом окне ход бота один
        norm = [" ".join(m["text"].lower().split()) for m in bot_turns]
        assert len(norm) == len(set(norm)), "дословный межходовый рефрен"


def test_threads_cover_every_message_exactly_once(dialog):
    """Серия разложена на треды без потерянных и дважды учтённых реплик."""
    data, _ = dialog
    seen = []
    for thread in data["threads"]:
        seen.extend(thread["members"])
    assert sorted(seen) == sorted(set(seen)), "сообщение попало в два треда"
    all_ids = [m["id"] for m in data["messages"]]
    missing = [i for i in all_ids if i not in seen]
    # Медиа и одиночные реплики могут не входить в смысловые треды — но тогда
    # они обязаны быть перечислены как «вне тредов» осознанно.
    assert set(missing) <= {"m4", "m8", "m11", "m16", "m21", "m22", "m23",
                            "m24"}, missing


def test_scenario_phrases_are_declared_absent_from_history(dialog):
    """Не подделываем сценарии: отсутствие в истории зафиксировано честно."""
    data, _ = dialog
    scenario = data["observability"]["scenario_phrases"]
    assert "рофлослав" in scenario["searched"]
    assert "диагноз" in scenario["searched"]
    assert scenario["conclusion"], "вывод об отсутствии сценариев обязателен"
    # Ни один ТЕКСТ реплики не содержит сценарных маркеров: иначе придуманный
    # диалог выдавался бы за исторический.
    texts = " ".join(m["text"] for m in data["messages"]).lower()
    for marker in ("рофлослав", "придумывал другой человек"):
        assert marker not in texts, marker
