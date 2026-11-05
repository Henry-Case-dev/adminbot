"""UR-23.4 (unified-reply): ledger published-output вЂ” РїРѕР»РЅР°СЏ С‚РµРєСЃС‚РѕРІР°СЏ
РёРґРµРЅС‚РёС„РёРєР°С†РёСЏ Р‘Р•Р— РјРѕР»С‡Р°Р»РёРІРѕРіРѕ preview РїРѕ [:20000].

РџРѕРєСЂС‹С‚РёРµ (services/summary_generator.py::_record_published_output):
  * summary РґР»РёРЅРЅРµРµ 20000 СЃРёРјРІРѕР»РѕРІ в†’ РІ `mca_bot_outputs` С…СЂР°РЅРёС‚СЃСЏ РџРћР›РќР«Р™
    РґРѕСЃС‚Р°РІР»РµРЅРЅС‹Р№ С‚РµРєСЃС‚ (СЂР°РІРµРЅСЃС‚РІРѕ Р±Р°Р№С‚-РІ-Р±Р°Р№С‚, С…РІРѕСЃС‚ РЅРµ СЃСЂРµР·Р°РЅ),
    content_hash СЃС‡РёС‚Р°РµС‚СЃСЏ РЅР°Рґ С‚РµРј Р¶Рµ РџРћР›РќР«Рњ С‚РµРєСЃС‚РѕРј, Рё content-hash
    Р±Р°СЂСЊРµСЂ (`find_bot_output_by_text`) РЅР°С…РѕРґРёС‚ Р·Р°РїРёСЃСЊ РїРѕ РїРѕР»РЅРѕРјСѓ
    plain-СЂРµРЅРґРµСЂСѓ вЂ” digest РЅРµ В«preview-С…РµС€В»;
  * РѕР±С‹С‡РЅС‹Р№ (РєРѕСЂРѕС‚РєРёР№) summary вЂ” РїРѕРІРµРґРµРЅРёРµ Р±РµР· РёР·РјРµРЅРµРЅРёР№ (С‚РµРєСЃС‚, С…РµС€,
    kind/correlation/source_feature);
  * digest-РєРѕРЅС‚СЂР°РєС‚: С…РµС€ СЃС‚СЂРѕРєРё РќР• СЃРѕРІРїР°РґР°РµС‚ СЃ С…РµС€РµРј preview-СЃСЂРµР·Р°
    [:20000] вЂ” РјСѓС‚Р°С†РёСЏ В«РІРµСЂРЅСѓС‚СЊ [:20000]В» РґРµР»Р°РµС‚ РґР»РёРЅРЅС‹Р№ С‚РµСЃС‚ РєСЂР°СЃРЅС‹Рј.
"""
from types import SimpleNamespace

import pytest

from config.settings import Settings
from services import bot_output_ledger as bol
from services.summary_generator import SummaryGenerator


@pytest.fixture(autouse=True)
def _ledger_on(monkeypatch):
    """Ledger ON (РїСЂРѕРґ-РґРµС„РѕР»С‚, С„РёРєСЃРёСЂСѓРµРј СЏРІРЅРѕ)."""
    monkeypatch.setattr(Settings, "MCA_BOT_OUTPUT_LEDGER_ENABLED", True,
                        raising=False)


async def _fresh(tmp_path, name="ledger_full.db"):
    from services.database import DatabaseService
    d = DatabaseService(str(tmp_path / name))
    await d.initialize()
    # `_record_published_output` РїРёС€РµС‚ С‡РµСЂРµР· default-binding ledger
    # (РїСЂРѕРґ: `setup_summary`) вЂ” РїСЂРёРІСЏР·С‹РІР°РµРј Рё С‡РµСЃС‚РЅРѕ РѕС‚РІСЏР·С‹РІР°РµРј.
    bol.bind_default_db(d)
    return d


def _gen_with_db(db) -> SummaryGenerator:
    gen = object.__new__(SummaryGenerator)     # Р±РµР· __init__ вЂ” С‚РѕР»СЊРєРѕ РїСѓС‚СЊ
    gen.memory = SimpleNamespace(db=db)
    gen.bot = SimpleNamespace(id=42)
    return gen


def _long_text() -> str:
    """РЎС‚Р°Р±РёР»СЊРЅС‹Р№ С‚РµРєСЃС‚ > 20000 СЃРёРјРІРѕР»РѕРІ СЃ СЂР°Р·Р»РёС‡РёРјС‹Рј С…РІРѕСЃС‚РѕРј."""
    body = "".join(
        f"РђР±Р·Р°С† {i:05d}: РѕСЃРјС‹СЃР»РµРЅРЅС‹Р№ С‚РµРєСЃС‚ РєРѕРЅСЃРїРµРєС‚Р° РґР»СЏ ledger-С‚РµСЃС‚Р°.\n\n"
        for i in range(700))
    return "РС‚РѕРі РІСЃС‚СЂРµС‡Рё\n\n" + body


@pytest.mark.asyncio
async def test_long_published_summary_stored_full_no_silent_preview(tmp_path):
    """(a) Published summary > 20000 СЃРёРјРІРѕР»РѕРІ в†’ ledger С…СЂР°РЅРёС‚ РџРћР›РќР«Р™ С‚РµРєСЃС‚,
    digest РЅР°Рґ РїРѕР»РЅС‹Рј С‚РµРєСЃС‚РѕРј, Р±Р°СЂСЊРµСЂ РЅР°С…РѕРґРёС‚ Р·Р°РїРёСЃСЊ; РЅРёРєР°РєРѕРіРѕ preview."""
    d = await _fresh(tmp_path, "long.db")
    gen = _gen_with_db(d)
    chat_id = -23041
    text = _long_text()
    assert len(text) > 20000

    await gen._record_published_output(
        chat_id, 900001, text, correlation_id="run-ur-23-4-long",
        source_feature="summary")

    row = await d.get_bot_output_by_tg(chat_id, 900001)
    assert row is not None
    # РџРћР›РќР«Р™ РґРѕСЃС‚Р°РІР»РµРЅРЅС‹Р№ С‚РµРєСЃС‚ вЂ” Р±Р°Р№С‚-РІ-Р±Р°Р№С‚, Р±РµР· СЃСЂРµР·Р° [:20000]:
    assert row["content_text"] == text
    assert len(row["content_text"]) == len(text)
    # С…РІРѕСЃС‚ СЂРµР°Р»СЊРЅРѕ РїСЂРёСЃСѓС‚СЃС‚РІСѓРµС‚ (РЅРµ preview):
    assert row["content_text"].endswith(text[-200:])
    # digest вЂ” РЅР°Рґ РџРћР›РќР«Рњ С‚РµРєСЃС‚РѕРј (С‚РѕС‚ Р¶Рµ material, С‡С‚Рѕ С…СЂР°РЅРёС‚СЃСЏ):
    assert row["content_hash"] == bol.content_hash(text)
    # content-hash Р±Р°СЂСЊРµСЂ: РїРѕРёСЃРє РїРѕ РїРѕР»РЅРѕРјСѓ plain-СЂРµРЅРґРµСЂСѓ РЅР°С…РѕРґРёС‚ Р·Р°РїРёСЃСЊ
    # (СѓСЂРµР·Р°РЅРЅС‹Р№ С…РµС€ РЅРµ СЃРѕРІРїР°Р» Р±С‹ вЂ” С‡РµСЃС‚РЅС‹Р№ digest РґР»СЏ РґР»РёРЅРЅС‹С… С‚РµРєСЃС‚РѕРІ):
    found = await bol.find_bot_output_by_text(d, chat_id, text)
    assert found is not None
    assert found["output_id"] == row["output_id"]
    await d.close()
    bol.bind_default_db(None)


@pytest.mark.asyncio
async def test_normal_size_summary_unchanged(tmp_path):
    """(b) РћР±С‹С‡РЅС‹Р№ (РєРѕСЂРѕС‚РєРёР№) summary вЂ” РїРѕРІРµРґРµРЅРёРµ Р±РµР· РёР·РјРµРЅРµРЅРёР№."""
    d = await _fresh(tmp_path, "short.db")
    gen = _gen_with_db(d)
    chat_id = -23042
    text = "РёС‚РѕРіРѕРІС‹Р№ С‚РµРєСЃС‚ summary"

    await gen._record_published_output(
        chat_id, 900002, text, correlation_id="run-ur-23-4-short",
        source_feature="summary")

    row = await d.get_bot_output_by_tg(chat_id, 900002)
    assert row is not None
    assert row["content_text"] == text
    assert row["content_hash"] == bol.content_hash(text)
    assert row["output_kind"] == "rich_message"
    assert row["correlation_id"] == "run-ur-23-4-short"
    assert row["source_feature"] == "summary"
    assert row["delivery_status"] == "delivered"
    found = await bol.find_bot_output_by_text(d, chat_id, text)
    assert found is not None
    await d.close()
    bol.bind_default_db(None)


@pytest.mark.asyncio
async def test_digest_is_full_text_not_preview_slice(tmp_path):
    """(c) Digest-РєРѕРЅС‚СЂР°РєС‚: content_hash СЃС‚СЂРѕРєРё = С…РµС€ РџРћР›РќРћР“Рћ С‚РµРєСЃС‚Р° Рё
    РќР• СЂР°РІРµРЅ С…РµС€Сѓ preview-СЃСЂРµР·Р° [:20000] вЂ” В«РІРµСЂРЅСѓС‚СЊ [:20000]В» Р»РѕРјР°РµС‚ (a)
    Рё СЌС‚РѕС‚ С‚РµСЃС‚ (РјСѓС‚Р°С†РёРѕРЅРЅР°СЏ РїР°СЂР°)."""
    d = await _fresh(tmp_path, "digest.db")
    gen = _gen_with_db(d)
    chat_id = -23043
    text = _long_text()
    assert len(text) > 20000

    await gen._record_published_output(
        chat_id, 900003, text, correlation_id="run-ur-23-4-digest",
        source_feature="summary")

    row = await d.get_bot_output_by_tg(chat_id, 900003)
    assert row is not None
    assert row["content_hash"] == bol.content_hash(text)
    assert row["content_hash"] != bol.content_hash(text[:20000])
    await d.close()
    bol.bind_default_db(None)
