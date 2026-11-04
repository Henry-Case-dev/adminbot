"""PVR-S3 — полная история версий: страницы, стабильный курсор, без потолка.

Контракт: ``plans/features/prompt-versioning-ux/arch/versioning-ux-contract.md``
§3 (полнота истории через существующий журнал), §5 (чтение без тел в списках),
§2.2/§2.4 п.9 (retired/несовместимые читаются, но не действуют).
Требования владельца: §2.2 п.3–5 (полный список страницами, источник/автор/
область/статус, полный текст отдельным запросом), §3.5 (без `HISTORY_MAX` и без
`LIMIT 50`, stable cursor, отзывчивость на 1000+), §3.7 (тел в списках нет,
RBAC global/чат).

Проверяется наблюдаемое поведение, а не наличие строк:

  1. обход 1000+ ревизий и 200+ событий страницами возвращает КАЖДУЮ запись
     ровно один раз, в детерминированном порядке, с непрерывной нумерацией и
     без потолка `50`;
  2. курсор стабилен: новые записи, появившиеся между страницами, не сдвигают
     и не дублируют уже выданные;
  3. список не содержит тел, тела отдаёт только авторизованный запрос по
     конкретной ревизии;
  4. чат-история не читается через другой чат;
  5. retired/несовместимая ревизия: читается, сравнивается, но не действует, с
     причиной; статус приходит в строке списка;
  6. N1: закреплённый scope (owner baseline) не перетирается первым размеченным
     релизом, даже если маркера импорта нет;
  7. N2: `copy-to-global` сообщает ФАКТИЧЕСКИ сохранённый `reason`;
  8. Speech-раздел берёт историю из журнала, а не из bounded-журнала на 12.

TEST-LIFECYCLE: CONTRACT owner=EPIC-PROMPT-VERSIONING-UX-01
"""
from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from services import prompt_factory as pf
from services import prompt_registry as pr
from services import prompt_release_policy as prp
from tests.test_evol016_prompt_activation import FakeCache, FactoryEdition
from tests.test_meme_pipeline_api import _build
from tests.test_webapp_api import ADMIN_ID, _hdr
from web.api import routes as routes_mod

BLOCK = "summary.base.narrator"
PG_KEY = "prompts.summary_narrator_system_prompt"

CHAT_A = -1009001
CHAT_B = -1009002

FACTORY_A = "ЗАВОДСКАЯ A: рассказчик саммари (эталон истории PVR-S3).\n"
FACTORY_B = ("ЗАВОДСКАЯ B: новая метка релиза — не должна заменить "
             "закреплённый владельцем scope.\n")
CHAT_A_TEXT = "ЧАТ A: собственный текст этого чата (история чата A).\n"
CHAT_B_TEXT = "ЧАТ B: собственный текст другого чата.\n"
COPIED_TEXT = "СКОПИРОВАННЫЙ ТЕКСТ: одинаковые байты из двух чатов.\n"


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture()
def edition(monkeypatch):
    patch = FactoryEdition(monkeypatch)
    patch.set_edition(BLOCK, "narrator-a", FACTORY_A)
    yield patch
    pr.set_release_policy_active(False)
    pr.set_retired_blocks(())
    pf._HISTORY_FROZEN = False
    pr.reset_cache()


@pytest.fixture()
def store():
    return prp.MemoryPromptJournal()


# ═══════════════════════════════════════════════════════════════════════════
# Стенд: синтетическая история 1000+ ревизий (без PG, тот же контракт стора)
# ═══════════════════════════════════════════════════════════════════════════

def _seed_bulk(store, *, revisions: int, activations: int,
               base_ts: str = "2026-01-01T00:00:00+00:00",
               chat_id: int | None = None) -> None:
    """Наполнить журнал предсказуемыми ревизиями/событиями.

    Метки времени монотонны с шагом в секунду, поэтому ожидаемый порядок
    вычисляется независимо от реализации страниц.
    """
    base = prp._parse_ts(base_ts)
    for idx in range(revisions):
        text = f"РЕВИЗИЯ {idx:04d}: текст версии номер {idx}.\n"
        ts = (base + __import__("datetime").timedelta(seconds=idx)).isoformat()
        revision_id = pr.revision_id_for(BLOCK,
                                         "chat" if chat_id is not None else
                                         "global", chat_id, "manual",
                                         pr.sha12(text))
        store.revisions[revision_id] = prp.RevisionRow(
            revision_id=revision_id, block_id=BLOCK,
            scope="chat" if chat_id is not None else "global",
            origin="manual", content_sha12=pr.sha12(text), body=text,
            pg_key=PG_KEY, chat_id=chat_id, actor=str(ADMIN_ID),
            reason="owner_edit", created_at=ts)
    for idx in range(activations):
        ts = (base + __import__("datetime").timedelta(
            seconds=idx, microseconds=500000)).isoformat()
        store.activations.append(prp.ActivationRow(
            block_id=BLOCK, scope="chat" if chat_id is not None else "global",
            kind="manual_edit", outcome="applied", revision_id="",
            actor=str(ADMIN_ID), detail_code="owner_edit", chat_id=chat_id,
            created_at=ts))


async def _walk(store, *, page_size: int, chat_id: int | None = None,
                limit_pages: int = 1000):
    """Пройти ВСЮ ленту курсором; вернуть (страницы, все записи, время)."""
    started = time.monotonic()
    cursor = None
    pages = []
    rows = []
    for _ in range(limit_pages):
        page = await store.list_history_page(BLOCK, chat_id=chat_id,
                                             cursor=cursor,
                                             page_size=page_size)
        pages.append(page)
        rows.extend(page.rows)
        if not page.has_more:
            return pages, rows, time.monotonic() - started
        cursor = prp.decode_history_cursor(page.next_cursor)
        assert cursor is not None
    raise AssertionError("обход истории не завершился — курсор не движется")


# ═══════════════════════════════════════════════════════════════════════════
# 1. 1000+ записей: полнота, порядок, отзывчивость, отсутствие потолка
# ═══════════════════════════════════════════════════════════════════════════

def test_full_history_of_1000_revisions_has_no_cap(store):
    """§3.5: потолка `50` нет — через страницы доступна ВСЯ история."""
    _seed_bulk(store, revisions=1000, activations=200)
    pages, rows, elapsed = _run(_walk(store, page_size=100))

    assert len(pages) == 12                      # 1200 записей / 100
    assert len(rows) == 1200, "история обрезана — часть записей недоступна"
    assert len({(r.entry_type, r.sort_id) for r in rows}) == 1200, \
        "страницы повторили записи"
    assert all(len(p.rows) <= 100 for p in pages), "размер страницы превышен"
    # Порядок детерминирован: строго по убыванию (created_at, вторичный ключ).
    keys = [(prp._norm_ts(r.created_at), r.sort_id) for r in rows]
    assert keys == sorted(keys, reverse=True), "порядок истории не детерминирован"
    assert rows[0].created_at == prp._norm_ts(
        max(r.created_at for r in rows)), "сверху не самая новая запись"
    assert elapsed < 10.0, f"обход 1200 записей слишком медленный: {elapsed:.2f}s"


def test_entries_have_continuous_order_numbers(store):
    """§2.2 п.3: у каждой строки есть порядковый номер, номера непрерывны."""
    _seed_bulk(store, revisions=120, activations=30)
    view = _run(prp.list_versions(BLOCK, store=store, actor="owner",
                                  page_size=50))

    first = view["entries"]
    assert len(first) == 50 and view["page"]["has_more"] is True
    assert [e["order"] for e in first] == list(range(1, 51))
    second = _run(prp.list_versions(BLOCK, store=store, actor="owner",
                                    page_size=50,
                                    cursor=view["page"]["next_cursor"]))
    assert [e["order"] for e in second["entries"]] == list(range(51, 101))
    assert not ({e["revision_id"] for e in first}
                & {e["revision_id"] for e in second["entries"]})


def test_cursor_is_stable_when_new_rows_appear(store):
    """§3.5: stable cursor — вставка новых записей не сдвигает страницы."""
    _seed_bulk(store, revisions=60, activations=0)
    snapshot = _run(_walk(store, page_size=10))[1]

    first = _run(store.list_history_page(BLOCK, page_size=10))
    seen = [r.sort_id for r in first.rows]
    # Между страницами появляются НОВЫЕ записи (свежее всех существующих).
    _seed_bulk(store, revisions=5, activations=0,
               base_ts="2026-06-01T00:00:00+00:00")

    cursor = prp.decode_history_cursor(first.next_cursor)
    second = _run(store.list_history_page(BLOCK, cursor=cursor, page_size=10))
    second_ids = [r.sort_id for r in second.rows]

    assert not (set(seen) & set(second_ids)), "вторая страница повторила записи"
    expected = [r.sort_id for r in snapshot[10:20]]
    assert second_ids == expected, "курсор «съехал»: записи пропущены или сдвинуты"
    # Порядковые номера продолжаются, а не пересчитываются заново.
    assert second.rank_start == 11


def test_list_never_contains_bodies(store):
    """§3.7 ТЗ: тел в списках нет; тело — только отдельным запросом."""
    _seed_bulk(store, revisions=3, activations=3)
    view = _run(prp.list_versions(BLOCK, store=store, actor="owner",
                                  page_size=50))
    raw = json.dumps(view, ensure_ascii=False)

    assert "РЕВИЗИЯ 0000" not in raw, "тело ревизии попало в список истории"
    assert "РЕВИЗИЯ 0002" not in raw
    revision_entries = [e for e in view["entries"]
                        if e["entry_type"] == prp.ENTRY_REVISION]
    assert revision_entries and all(e["body_available"] for e in revision_entries)
    assert all(e["chars"] > 0 for e in revision_entries)

    source = _run(prp.get_revision_source(revision_entries[0]["revision_id"],
                                          store=store, actor="owner"))
    assert source["known"] is True
    assert "РЕВИЗИЯ 0002" in source["body"], "полный текст недоступен"


def test_legacy_lists_are_paged_without_cap(store):
    """`revisions`/`activations` листаются своими курсорами и не режутся на 50."""
    _seed_bulk(store, revisions=70, activations=70)
    view = _run(prp.list_versions(BLOCK, store=store, actor="owner",
                                  page_size=50))
    assert len(view["revisions"]) == 50
    assert view["revisions_page"]["has_more"] is True
    assert view["revisions_page"]["order"] == prp.HISTORY_ORDER_OLDEST
    # Исторический порядок ревизий сохранён: старые сверху.
    assert view["revisions"][0]["created_at"] <= view["revisions"][-1]["created_at"]

    rows = list(view["revisions"])
    cursor = view["revisions_page"]["next_cursor"]
    while cursor:
        page = _run(prp.list_versions(BLOCK, store=store, actor="owner",
                                      page_size=50, revisions_cursor=cursor))
        rows.extend(page["revisions"])
        cursor = page["revisions_page"]["next_cursor"]
    assert len({r["revision_id"] for r in rows}) == 70

    events = []
    cursor = ""
    batch = _run(prp.list_versions(BLOCK, store=store, actor="owner",
                                   page_size=50))["activations"]
    events.extend(batch)
    cursor = _run(prp.list_versions(BLOCK, store=store, actor="owner",
                                    page_size=50))["activations_page"]["next_cursor"]
    while cursor:
        page = _run(prp.list_versions(BLOCK, store=store, actor="owner",
                                      page_size=50,
                                      activations_cursor=cursor))
        events.extend(page["activations"])
        cursor = page["activations_page"]["next_cursor"]
    assert len(events) == 70, "события активаций обрезаны потолком"


def test_revisions_first_page_is_newest_and_paging_goes_deeper(store):
    """Первая страница `revisions` — свежие правки; курсор ведёт вглубь."""
    _seed_bulk(store, revisions=70, activations=0)
    view = _run(prp.list_versions(BLOCK, store=store, actor="owner",
                                  page_size=50))
    rows = view["revisions"]
    newest = max(prp._norm_ts(r.created_at) for r in store.revisions.values())
    assert prp._norm_ts(rows[-1]["created_at"]) == newest, \
        "самая свежая ревизия не попала на первую страницу"
    assert view["revisions_page"]["paging"] == prp.HISTORY_ORDER_NEWEST
    deeper = _run(prp.list_versions(BLOCK, store=store, actor="owner",
                                   page_size=50,
                                   revisions_cursor=view["revisions_page"]
                                   ["next_cursor"]))
    assert deeper["revisions_page"]["has_more"] is False
    assert len(deeper["revisions"]) == 20
    assert max(r["created_at"] for r in deeper["revisions"]) < \
        min(r["created_at"] for r in rows), "вглубь истории попали не старые"


# ═══════════════════════════════════════════════════════════════════════════
# 2. Источник/статус/автор/область в строке (§2.2 п.3)
# ═══════════════════════════════════════════════════════════════════════════

def test_entry_carries_source_actor_scope_and_status(edition, store):
    """§2.2 п.3: источник, автор, область и статус приходят в самой строке."""
    cache = FakeCache({PG_KEY: FACTORY_A})
    _run(prp.apply_release(cache, release_id="evol-016-cutover", store=store,
                          blocks=[BLOCK]))
    _run(prp.write_versioned_value(BLOCK, "РУЧНАЯ M: правка владельца.\n",
                                   cache=cache, store=store, actor="owner"))
    factory = next(r for r in store.revisions.values() if r.origin == "factory")
    _run(prp.assign_baseline(BLOCK, factory.revision_id, actor="owner",
                             cache=cache, store=store))
    view = _run(prp.list_versions(BLOCK, store=store, actor="owner",
                                  page_size=50))
    by_id = {e["revision_id"]: e for e in view["entries"]
             if e["entry_type"] == prp.ENTRY_REVISION}

    assert by_id[factory.revision_id]["source"] == "from_release"
    assert by_id[factory.revision_id]["status"] == "baseline"
    assert by_id[factory.revision_id]["source_label"] == "из релиза"
    assert by_id[factory.revision_id]["actionable"] is True
    manual = next(r for r in store.revisions.values() if r.origin == "manual")
    assert by_id[manual.revision_id]["source"] == "manual"
    assert by_id[manual.revision_id]["actor"] == "owner"
    assert by_id[manual.revision_id]["scope"] == "global"
    active = _run(store.read_applied(BLOCK, "global", None))
    assert by_id[active.revision_id]["status"] == "active"
    legacy = [r for r in store.revisions.values() if r.origin == "legacy"]
    for row in legacy:
        assert by_id[row.revision_id]["source"] == "imported"


def test_retired_and_incompatible_are_readable_but_never_actionable(
        edition, store):
    """§2.4 п.9 / §2.2 п.8: статус, причина и запрет действия — в строке."""
    cache = FakeCache({PG_KEY: FACTORY_A})
    _run(prp.apply_release(cache, release_id="evol-016-cutover", store=store,
                          blocks=[BLOCK]))
    retired_row = next(r for r in store.revisions.values()
                       if r.origin == "factory")
    retired_row.retired = True
    bad_text = "НЕСОВМЕСТИМАЯ S: schema_compat вне SUPPORTED.\n"
    bad_id = pr.revision_id_for(BLOCK, "global", None, "manual",
                                pr.sha12(bad_text))
    store.revisions[bad_id] = prp.RevisionRow(
        revision_id=bad_id, block_id=BLOCK, scope="global", origin="manual",
        content_sha12=pr.sha12(bad_text), body=bad_text, pg_key=PG_KEY,
        schema_compat="schema-from-the-future", actor="owner",
        created_at="2026-03-01T00:00:00+00:00")

    view = _run(prp.list_versions(BLOCK, store=store, actor="owner",
                                  page_size=50))
    by_id = {e["revision_id"]: e for e in view["entries"]
             if e["entry_type"] == prp.ENTRY_REVISION}
    assert by_id[retired_row.revision_id]["status"] == "retired"
    assert by_id[retired_row.revision_id]["actionable"] is False
    assert "снята с регистрации" in by_id[retired_row.revision_id]["reason_text"]
    assert by_id[bad_id]["status"] == "incompatible"
    assert by_id[bad_id]["actionable"] is False
    assert "Несовместима" in by_id[bad_id]["reason_text"]
    # Читать и сравнивать — можно.
    assert _run(prp.get_revision_source(bad_id, store=store,
                                        actor="owner"))["body"] == bad_text
    diff = _run(prp.diff_revisions(retired_row.revision_id, bad_id,
                                   store=store, actor="owner"))
    assert diff["known"] is True and diff["diff"]
    assert diff["actionable"] is False and diff["reason_text"]


def test_event_rows_agree_with_their_revision_state(edition, store):
    """B1 (§2.4 п.9, §2.2 п.8): событие и его ревизия — ОДИН статус.

    Ревью PVR-S3 (B1): строка-событие считала статус только по самому событию,
    поэтому `manual_edit`/`baseline_assign` на снятой с регистрации версии
    показывали `active` + «Применить», а строка той же версии — `retired` и
    запрет действия. S4 строит из этих строк один список, значит состояние
    обязано совпадать, а причина — быть честной.
    """
    cache = FakeCache({PG_KEY: FACTORY_A})
    _run(prp.apply_release(cache, release_id="evol-016-cutover", store=store,
                           blocks=[BLOCK]))

    retired_text = "СНЯТАЯ R: правка владельца, затем retired.\n"
    _run(prp.write_versioned_value(BLOCK, retired_text, cache=cache,
                                   store=store, actor="owner"))
    retired_row = next(r for r in store.revisions.values()
                       if r.content_sha12 == pr.sha12(retired_text))
    _run(prp.assign_baseline(BLOCK, retired_row.revision_id, actor="owner",
                             cache=cache, store=store))
    # Снята с регистрации ПОСЛЕ событий: берём ЖИВУЮ строку стора (транзакция
    # назначения клонирует состояние, прежняя ссылка уже отвязана).
    retired_row = store.revisions[retired_row.revision_id]
    retired_row.retired = True

    bad_text = "НЕСОВМЕСТИМАЯ S: schema_compat вне SUPPORTED.\n"
    bad_id = pr.revision_id_for(BLOCK, "global", None, "manual",
                                pr.sha12(bad_text))
    store.revisions[bad_id] = prp.RevisionRow(
        revision_id=bad_id, block_id=BLOCK, scope="global", origin="manual",
        content_sha12=pr.sha12(bad_text), body=bad_text, pg_key=PG_KEY,
        schema_compat="schema-from-the-future", actor="owner",
        created_at="2026-03-01T00:00:00+00:00")
    store.activations.append(prp.ActivationRow(
        block_id=BLOCK, scope="global", kind="manual_edit", outcome="applied",
        revision_id=bad_id, actor="owner", detail_code="owner_edit",
        created_at="2026-03-01T00:00:00+00:00"))

    view = _run(prp.list_versions(BLOCK, store=store, actor="owner",
                                  page_size=50))
    revision_state = {e["revision_id"]:
                      (e["status"], e["actionable"], e["reason_text"])
                      for e in view["entries"]
                      if e["entry_type"] == prp.ENTRY_REVISION}

    def _events(revision_id: str) -> list:
        return [e for e in view["entries"]
                if e["entry_type"] == prp.ENTRY_ACTIVATION
                and e["revision_id"] == revision_id]

    retired_events = _events(retired_row.revision_id)
    assert {e["kind"] for e in retired_events} == {"manual_edit",
                                                   "baseline_assign"}
    for event in retired_events:
        assert event["status"] == "retired", "событие на снятой версии «активно»"
        assert event["actionable"] is False, \
            "S4 предложил бы «Применить» для снятой версии"
        assert "снята с регистрации" in event["reason_text"]
        assert (event["status"], event["actionable"],
                event["reason_text"]) == revision_state[
                    retired_row.revision_id], \
            "строка события противоречит строке своей ревизии"

    bad_events = _events(bad_id)
    assert bad_events, "событие несовместимой ревизии не попало в ленту"
    for event in bad_events:
        assert event["status"] == "incompatible"
        assert event["actionable"] is False
        assert "Несовместима" in event["reason_text"]
        assert (event["status"], event["actionable"],
                event["reason_text"]) == revision_state[bad_id]

    # Второй список того же ответа (`activations`) говорит то же самое.
    legacy_events = [a for a in view["activations"]
                     if a["revision_id"] == retired_row.revision_id]
    assert legacy_events
    assert all(a["status"] == "retired" and a["actionable"] is False
               for a in legacy_events)

    # N-3: событие назначения базовой — не «восстановлена» (токен контракта
    # `restored` не менялся, уточнена только человеческая подпись).
    assign = next(e for e in retired_events if e["kind"] == "baseline_assign")
    assert assign["source"] == "restored"
    assert assign["source_label"] == "назначена базовая"


def test_chat_history_is_not_readable_through_another_chat(store):
    """§3.7 ТЗ / §2.4 п.5: история чата не видна из другого чата."""
    _seed_bulk(store, revisions=3, activations=2, chat_id=CHAT_A)
    _seed_bulk(store, revisions=2, activations=1, chat_id=CHAT_B)
    own = _run(prp.list_versions(BLOCK, scope="chat", chat_id=CHAT_A,
                                 store=store, actor="owner", page_size=50))
    alien = _run(prp.list_versions(BLOCK, scope="chat", chat_id=CHAT_B,
                                   store=store, actor="owner", page_size=50))
    global_view = _run(prp.list_versions(BLOCK, scope="global", store=store,
                                         actor="owner", page_size=50))

    assert len(own["entries"]) == 5
    assert len(alien["entries"]) == 3
    assert global_view["entries"] == [], "чатовая история просочилась в global"
    assert all(e["chat_id"] == CHAT_A for e in own["entries"]
               if e["entry_type"] == prp.ENTRY_REVISION)
    assert not ({e["revision_id"] for e in own["entries"] if e["revision_id"]}
                & {e["revision_id"] for e in alien["entries"]
                   if e["revision_id"]})


# ═══════════════════════════════════════════════════════════════════════════
# 3. HTTP: page_size/cursor, 422 на испорченный курсор
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture()
def env(monkeypatch):
    patch = FactoryEdition(monkeypatch)
    patch.set_edition(BLOCK, "narrator-a", FACTORY_A)
    conn, cache, app = _build(monkeypatch)
    journal = prp.MemoryPromptJournal()
    monkeypatch.setattr(routes_mod, "_prompt_journal", lambda cache_: journal)
    monkeypatch.setattr(prp, "default_journal", lambda cache_: journal)
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, cache=cache, journal=journal,
                              edition=patch)
    pr.set_release_policy_active(False)
    pr.set_retired_blocks(())
    pf._HISTORY_FROZEN = False
    pr.reset_cache()


def _headers(chat_id: int | None = None, user_id: int = ADMIN_ID):
    headers = _hdr(user_id)
    if chat_id is not None:
        headers["X-Chat-Id"] = str(chat_id)
    return headers


def test_api_versions_paginates_through_whole_history(env):
    """§3.5: HTTP-история листается курсором, суммарно отдаёт все записи."""
    _seed_bulk(env.journal, revisions=120, activations=30)
    resp = env.client.get(f"/api/prompts/{PG_KEY}/versions?page_size=25",
                          headers=_headers())
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["page"]["page_size"] == 25
    assert payload["page"]["order"] == "newest_first"
    assert payload["page"]["has_more"] is True

    ids = [(e["entry_type"], e["revision_id"], e["order"])
           for e in payload["entries"]]
    cursor = payload["page"]["next_cursor"]
    pages = 1
    while cursor:
        nxt = env.client.get(
            f"/api/prompts/{PG_KEY}/versions?page_size=25&cursor={cursor}",
            headers=_headers())
        assert nxt.status_code == 200, nxt.text
        body = nxt.json()
        ids.extend((e["entry_type"], e["revision_id"], e["order"])
                   for e in body["entries"])
        cursor = body["page"]["next_cursor"]
        pages += 1
    assert pages == 6 and len(ids) == 150
    assert [row[2] for row in ids] == list(range(1, 151))
    assert len({(row[0], row[1], row[2]) for row in ids}) == 150


def test_api_versions_rejects_broken_cursor(env):
    """Испорченный курсор — 422 запроса, а не «история пуста»/500."""
    _seed_bulk(env.journal, revisions=3, activations=0)
    resp = env.client.get(f"/api/prompts/{PG_KEY}/versions?cursor=not-a-cursor",
                          headers=_headers())
    assert resp.status_code == 422, resp.text
    assert "курсор" in resp.json()["detail"]


def test_api_versions_page_size_is_clamped_not_capping_history(env):
    """`page_size` — размер страницы: 0 → дефолт, 1000 → максимум 200."""
    _seed_bulk(env.journal, revisions=210, activations=0)
    zero = env.client.get(f"/api/prompts/{PG_KEY}/versions?page_size=0",
                          headers=_headers()).json()
    assert zero["page"]["page_size"] == prp.HISTORY_PAGE_DEFAULT
    huge = env.client.get(f"/api/prompts/{PG_KEY}/versions?page_size=1000",
                          headers=_headers()).json()
    assert huge["page"]["page_size"] == prp.HISTORY_PAGE_MAX
    assert len(huge["entries"]) == prp.HISTORY_PAGE_MAX
    assert huge["page"]["has_more"] is True, "история обрезана размером страницы"


def test_api_chat_history_is_isolated(env):
    """§3.7: через другой чат история не читается (не пустой ответ, а своя)."""
    _seed_bulk(env.journal, revisions=2, activations=1, chat_id=CHAT_A)
    mine = env.client.get(f"/api/prompts/{PG_KEY}/versions",
                          headers=_headers(CHAT_A))
    assert mine.status_code == 200, mine.text
    assert len(mine.json()["entries"]) == 3
    global_view = env.client.get(f"/api/prompts/{PG_KEY}/versions",
                                 headers=_headers())
    assert global_view.json()["entries"] == []


# ═══════════════════════════════════════════════════════════════════════════
# 4. N1: закреплённый scope не перетирается первым размеченным релизом
# ═══════════════════════════════════════════════════════════════════════════

def _seed_global_revision(store, text: str, *, origin="restored"):
    revision_id = pr.revision_id_for(BLOCK, "global", None, origin,
                                     pr.sha12(text))
    store.revisions[revision_id] = prp.RevisionRow(
        revision_id=revision_id, block_id=BLOCK, scope="global", origin=origin,
        content_sha12=pr.sha12(text), body=text, pg_key=PG_KEY,
        reason="copied_from_chat:rev-chat-a",
        created_at="2026-02-01T00:00:00+00:00")
    return store.revisions[revision_id]


def test_pinned_scope_first_labelled_release_keeps_value(edition, store):
    """РЕВЬЮ PVR-S2 N1: pinned + нет значения + нет маркера импорта.

    Ревизия пришла через copy-to-global, импортировать было нечего — раньше
    первый размеченный релиз шёл по cutover и писал заводской текст, обходя
    закрепление. Теперь — `activate_pinned`: ревизия в историю, значение нет.
    """
    revision = _seed_global_revision(store, "КОПИЯ: текст, пришедший из чата.\n")
    cache = FakeCache({})                       # значения в scope НЕТ
    _run(prp.assign_baseline(BLOCK, revision.revision_id, actor="owner",
                             cache=cache, store=store))
    # Маркера импорта нет: импортировать было нечего (ревизия пришла копией).
    assert _run(store.has_import(BLOCK, "global", None)) is False

    edition.set_edition(BLOCK, "narrator-b", FACTORY_B)   # новая метка релиза
    result = _run(prp.apply_release(cache, release_id="release-b", store=store,
                                    blocks=[BLOCK]))

    row = next(r for r in result["results"]
               if r.action == pr.PLAN_ACTIVATE_PINNED)
    assert row.outcome == "skipped_same"
    assert row.detail_code == "factory_superseded_pinned"
    # Заводской текст НЕ стал действующим значением.
    assert cache.values.get(PG_KEY) in (None, "")
    assert _run(store.read_global(PG_KEY)) in (None, "")
    # ...но ревизия новой заводской метки в истории есть.
    factory_rows = [r for r in store.revisions.values()
                    if r.origin == "factory"
                    and r.content_sha12 == pr.sha12(FACTORY_B)]
    assert factory_rows, "заводская ревизия не записана в историю"
    applied = _run(store.read_applied(BLOCK, "global", None))
    assert applied.factory_revision_applied == pr.FACTORY_PREFIX + \
        pr.sha12("narrator-b")
    # Активного текста в scope не было — указатель baseline не подменяется.
    assert applied.revision_id == ""
    state = _run(prp.read_baseline(BLOCK, cache=cache, store=store,
                                   actor="owner"))
    assert state["baseline"]["revision_id"] == revision.revision_id
    # Повторный запуск — истинный no-op (ни событий, ни ревизий).
    before = (len(store.activations), len(store.revisions))
    _run(prp.apply_release(cache, release_id="release-b", store=store,
                          blocks=[BLOCK]))
    assert (len(store.activations), len(store.revisions)) == before


def test_pinned_scope_snapshots_untracked_text(edition, store):
    """N1 (вторая половина): снимок текущих байтов не теряется в pinned-ветке."""
    revision = _seed_global_revision(store, "КОПИЯ: текст из чата.\n")
    untracked = "РУЧНОЙ ТЕКСТ ВНЕ ЖУРНАЛА: должен попасть в историю.\n"
    cache = FakeCache({PG_KEY: untracked})
    _run(prp.assign_baseline(BLOCK, revision.revision_id, actor="owner",
                             cache=cache, store=store))
    edition.set_edition(BLOCK, "narrator-b", FACTORY_B)

    _run(prp.apply_release(cache, release_id="release-b", store=store,
                          blocks=[BLOCK]))

    legacy = [r for r in store.revisions.values()
              if r.origin == "legacy" and r.content_sha12 == pr.sha12(untracked)]
    assert legacy, "текущий ручной текст не снят в историю"
    assert cache.values[PG_KEY] == untracked, "закреплённый текст перетёрт"
    kinds = [(a.kind, a.detail_code) for a in store.activations]
    assert ("legacy_import", "legacy_snapshot") in kinds


# ═══════════════════════════════════════════════════════════════════════════
# 5. N2: copy-to-global отдаёт фактически сохранённый reason
# ═══════════════════════════════════════════════════════════════════════════

def test_copy_to_global_reports_stored_reason(edition, store):
    """РЕВЬЮ PVR-S2 N2: ответ и журнал говорят одно и то же про источник."""
    cache = FakeCache({PG_KEY: FACTORY_A})
    _run(prp.apply_release(cache, release_id="evol-016-cutover", store=store,
                          blocks=[BLOCK]))
    _run(prp.write_versioned_value(BLOCK, CHAT_A_TEXT, scope="chat",
                                   chat_id=CHAT_A, cache=cache, store=store,
                                   actor="owner"))
    _run(prp.write_versioned_value(BLOCK, COPIED_TEXT, scope="chat",
                                   chat_id=CHAT_A, cache=cache, store=store,
                                   actor="owner"))
    _run(prp.write_versioned_value(BLOCK, COPIED_TEXT, scope="chat",
                                   chat_id=CHAT_B, cache=cache, store=store,
                                   actor="owner"))
    rev_a = _run(store.find_revision_by_sha(BLOCK, pr.sha12(COPIED_TEXT),
                                            chat_id=CHAT_A))
    rev_b = _run(store.find_revision_by_sha(BLOCK, pr.sha12(COPIED_TEXT),
                                            chat_id=CHAT_B))
    assert rev_a is not None and rev_b is not None

    first = _run(prp.copy_revision_to_global(BLOCK, rev_a.revision_id,
                                            actor="owner", cache=cache,
                                            store=store))
    assert first["created"] is True
    assert first["copy_reason"] == f"copied_from_chat:{rev_a.revision_id}"

    second = _run(prp.copy_revision_to_global(BLOCK, rev_b.revision_id,
                                             actor="owner", cache=cache,
                                             store=store))
    stored = _run(store.get_revision(second["revision_id"]))
    assert second["created"] is False
    assert second["copy_reason"] == stored.reason, \
        "ответ сообщает не тот провенанс, что сохранён в журнале"
    assert second["copy_reason"] == f"copied_from_chat:{rev_a.revision_id}"


# ═══════════════════════════════════════════════════════════════════════════
# 6. Speech: история из журнала, без bounded-журнала на 12
# ═══════════════════════════════════════════════════════════════════════════

def test_speech_history_comes_from_journal_without_12_cap(monkeypatch, store):
    """§3.5 + §2.2 п.3: в Speech-разделе больше нет второго журнала на 12."""
    from web.api import speech as speech_mod
    monkeypatch.setattr(prp, "default_journal", lambda cache_: store)
    monkeypatch.setattr(pf, "_default_cache", lambda: FakeCache({}))
    monkeypatch.setattr(pf, "_HISTORY_FROZEN", True)
    _seed_bulk(store, revisions=45, activations=10)
    cache = FakeCache({})
    user = SimpleNamespace(id=ADMIN_ID)

    view = _run(speech_mod._prompt_history_view(cache, user, [BLOCK],
                                                chat_id=None))
    assert view["source"] == "journal"
    assert len(view["rows"]) == 50, "история Speech обрезана потолком"
    assert view["pages"][BLOCK]["has_more"] is True
    small = _run(speech_mod._prompt_history_view(cache, user, [BLOCK],
                                                 chat_id=None, page_size=13))
    assert len(small["rows"]) == 13
    row = small["rows"][0]
    for key in ("revision", "kind", "scope", "sha256_12", "chars",
                "updated_at", "actor", "reason"):
        assert key in row, f"прежний ключ строки истории пропал: {key}"
    assert row["source"] and row["status"] and row["entry_type"]


def test_speech_history_falls_back_to_legacy_only_without_journal(monkeypatch):
    """§0.3 ТЗ: старая ограниченная история — честная граница, не «полная»."""
    from web.api import speech as speech_mod
    monkeypatch.setattr(prp, "default_journal", lambda cache_: None)
    legacy_cache = FakeCache({})

    async def _fake_history(block_id, *, cache=None):
        return [{"revision": "act:abc", "kind": "factory_reset",
                 "scope": "global", "sha256_12": "abc", "chars": 3,
                 "updated_at": "2026-01-01T00:00:00+00:00", "actor": "owner",
                 "reason": "factory_reset"}]
    monkeypatch.setattr(pf, "history_for", _fake_history)
    view = _run(speech_mod._prompt_history_view(legacy_cache,
                                                SimpleNamespace(id=ADMIN_ID),
                                                [BLOCK], chat_id=None))
    assert view["available"] is False and view["rows"] == []
    fallback = _run(speech_mod._legacy_history_rows(legacy_cache, [BLOCK]))
    assert fallback["source"] == "legacy_bounded"
    assert len(fallback["rows"]) == 1
