"""Детерминированные фикстуры «Когнитивной карты» для приёмки EPIC-CM-VISUAL-01 (§10.2).

Требование спеки §10.2: проверять РЕАЛЬНЫЕ размеры — **10 / 100 / 702 узла
с 2400 рёбрами**, последний по реальной либо семантически обезличенной копии
текущей топологии, а не пустую сетку.

Здесь одна функция-источник: `payload(nodes_n, edges_n=2400, seed=...)`.
Коммитнутые рядом `cog_map_10.json`, `cog_map_100.json`, `cog_map_702.json` —
её же вывод (`generated_at: null`), поэтому стенды читают готовые данные, а
`tests/test_cmv_e_fixtures.py` сверяет файлы с генератором побайтово. Так
фикстура воспроизводима и не может незаметно разойтись с кодом.

Топология — семантически обезличенная модель реального «плотного» чата:
несколько сообществ (тем) с плотными внутренними связями и редкими мостами
между ними. Никаких настоящих имён, id чатов и текстов сообщений: заголовки
составлены из нейтральных бытовых фраз, id синтетические.

Крайние случаи §11, которые фикстура обязана нести как ДАННЫЕ:
  * одинаковые имена у разных узлов (`same name`);
  * очень длинная русская подпись;
  * изолированные узлы (без связей);
  * несколько связей между одной парой (у 10-узловой фикстуры 2400 рёбер
    ложатся на 45 различимых пар — это и есть «много связей между одной парой»);
  * отсутствующие метаданные (у части узлов нет `status`/`time`).
"""
import hashlib
import json
import os

#: Тот же чат-скоуп, что у живых стендов W15/CMV-B/C/D (число, не секрет).
CHAT = -1001234567890

#: Обязательный набор размеров §10.2.
SIZES = (10, 100, 702)
#: Число связей в каждой фикстуре §10.2 (одинаковое для всех размеров).
EDGES = 2400

KIND_PLAN = (
    ("fact", 45), ("belief", 20), ("entity", 15), ("paradigm", 8),
    ("observation", 7), ("evolution_event", 5),
)

PREFIX = {"fact": "fact", "belief": "belief", "paradigm": "paradigm",
          "entity": "ent", "observation": "obs", "evolution_event": "evt"}

TITLES = (
    "Утро начинается с кофе", "Костя играет в шахматы", "Дача — место отдыха",
    "Аня любит утренний кофе", "Разговор о работе и усталости",
    "Планы на выходные: поездка за город", "Доверие строится постепенно",
    "Бережёт утро и не любит ранние звонки", "Факт уточнён после проверки",
    "Шутка про понедельник", "Память о поездке в Карелию",
    "Долгая и подробная запись о том, как человек реагирует на критику "
    "и почему это важно помнить в разговоре",
    "same name", "same name", "same name",
)

RELATIONS = ("обсуждали", "derived_from", "revised_by")


def _lcg(seed):
    """Линейный конгруэнтный генератор: воспроизводимо на любой платформе."""
    state = {"v": seed & 0x7FFFFFFF}

    def nxt(limit):
        state["v"] = (state["v"] * 1103515245 + 12345) & 0x7FFFFFFF
        return (state["v"] >> 7) % limit

    return nxt


def _kind_for(i):
    total = sum(w for _, w in KIND_PLAN)
    pos = i % total
    for kind, weight in KIND_PLAN:
        if pos < weight:
            return kind
        pos -= weight
    return "other"


def _communities(nodes_n):
    """Число сообществ по размеру набора (одна и та же логика для всех).

    10 узлов — 2 темы, 100 — 5, 702 — 6 (как реальный плотный чат стенда B).
    """
    if nodes_n <= 12:
        return 2
    if nodes_n <= 120:
        return 5
    return 6


def nodes_of(nodes_n):
    """Узлы фикстуры: та же форма, что отдаёт `GET /api/memory/cognitive-map`."""
    islands = {3} if nodes_n >= 10 else set()
    out = []
    for i in range(nodes_n):
        kind = _kind_for(i)
        nid = "%s:%d:%d" % (PREFIX[kind], CHAT, i + 1)
        # §11: часть записей без метаданных — вид обязан это пережить.
        bare = (i % 37 == 11)
        out.append({
            "id": nid,
            "kind": kind,
            "scope": "chat",
            "chat_id": CHAT,
            "title": "%s %d" % (TITLES[i % len(TITLES)], i + 1),
            "text": "запись %d" % (i + 1),
            "status": None if bare else "confirmed",
            "isolated": i in islands,
            "time": None if bare else {
                "occurred_at": 1750000000 + i, "observed_at": None,
                "saved_at": 1750000100 + i, "confirmed_at": None,
                "updated_at": None,
            },
            "provenance": {"record": "graph_facts", "chat_id": CHAT,
                           "message_id": 500 + i, "origin": "chat_history",
                           "fact_id": i + 1},
            "metrics": {"importance": (i % 10) + 1, "weight": None,
                        "degree": None},
            "refs": {},
        })
    return out


def edges_of(nodes, edges_n=EDGES, seed=20261103):
    """Рёбра: кольца сообществ, локальные хабы, мосты, добор до `edges_n`."""
    ids = [n["id"] for n in nodes]
    isolated = {n["id"] for n in nodes if n["isolated"]}
    pool = [i for i in ids if i not in isolated]
    nxt = _lcg(seed)
    pairs = []
    used = set()

    def add(a, b):
        if a == b or a in isolated or b in isolated:
            return False
        key = (a, b)
        if key in used:
            return False
        used.add(key)
        pairs.append(key)
        return True

    groups = _communities(len(nodes))
    size = max(1, len(pool) // groups)
    for c in range(groups):
        lo = c * size
        hi = (lo + size) if c < groups - 1 else len(pool)
        members = pool[lo:hi]
        if len(members) < 2:
            continue
        for i, nid in enumerate(members):                 # кольцо: связность
            add(nid, members[(i + 1) % len(members)])
        for i, nid in enumerate(members):                 # локальные хабы
            for _ in range(3):
                add(nid, members[nxt(len(members))])
        for i in range(0, len(members), 29):               # центры тем
            add(members[i], members[(i + 7) % len(members)])
    for c in range(groups):                                # мосты между темами
        other = (c + 1) % groups
        a = pool[min(len(pool) - 1, c * size)]
        b = pool[min(len(pool) - 1, other * size + 3)]
        add(a, b)

    # Добор: случайные пары. У 10-узловой фикстуры различимых пар всего 45,
    # поэтому остаток — РЕАЛЬНЫЕ повторные связи между теми же парами (§11).
    guard = 0
    while len(pairs) < edges_n and guard < edges_n * 40:
        guard += 1
        a = pool[nxt(len(pool))]
        b = pool[nxt(len(pool))]
        if a == b:
            continue
        pairs.append((a, b))

    out = []
    for i, (a, b) in enumerate(pairs[:edges_n]):
        derived = (i % 3 == 0)
        out.append({
            "id": "ce%d" % (i + 1),
            "from": a,
            "to": b,
            "relation": ("revised_by" if i % 37 == 0
                         else (RELATIONS[1] if derived else RELATIONS[0])),
            "derived": derived,
            "chat_id": CHAT,
            "justification_recorded": (i % 11 != 0),
            "provenance": {"fact_id": i + 1},
        })
    return out


def payload(nodes_n, edges_n=EDGES, seed=20261103, generated_at=None):
    """Полный ответ `cog-map/1` нужного размера (детерминированный)."""
    nodes = nodes_of(nodes_n)
    edges = edges_of(nodes, edges_n=edges_n, seed=seed)
    paired = {(e["from"], e["to"]) for e in edges}
    return {
        "version": "cog-map/1",
        "generated_at": generated_at,
        "state": "partial",
        "scope": {"mode": "chat", "chat_id": CHAT},
        "degraded": {"active": False, "not_loaded": []},
        "sources": {"facts": "loaded", "graph": "loaded"},
        "caps": {"nodes": 800, "edges": edges_n, "per_class": 150,
                 "classes": 4, "entity_nodes": 796},
        "shown_of": {
            "nodes": len(nodes),
            "edges": len(edges),
            "totals": {"nodes": max(1, int(round(nodes_n * 74.9))),
                       "edges": max(1, int(round(edges_n * 40.8)))},
            "unresolved_refs": 0,
            # Число различимых пар связей: у плотных малых наборов оно меньше
            # числа рёбер, и это ЧЕСТНАЯ метрика фикстуры, а не ошибка.
            "distinct_pairs": len(paired),
            "by_kind": {
                "fact": {"shown": 316, "total": 24000, "truncated": True},
                "belief": {"shown": 140, "total": 9000, "truncated": True},
                "paradigm": {"shown": 56, "total": 400, "truncated": True},
                "entity": {"shown": 105, "total": 19000, "truncated": True},
            },
        },
        "truncated": {"nodes": True, "edges": True,
                      "by_class": {"fact": True, "belief": True,
                                   "paradigm": True, "evolution": True,
                                   "entity": True}},
        "nodes": nodes,
        "edges": edges,
    }


def canonical(payload_obj):
    """Каноническая сериализация: файл фикстуры = ровно это."""
    return json.dumps(payload_obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def sha256(payload_obj):
    return hashlib.sha256(canonical(payload_obj).encode("utf-8")).hexdigest()


def path_for(nodes_n, root=None):
    here = os.path.dirname(os.path.abspath(__file__))
    base = root or here
    return os.path.join(base, "cog_map_%d.json" % nodes_n)


def load(nodes_n, root=None):
    """Прочитать коммитнутую фикстуру как dict."""
    with open(path_for(nodes_n, root), encoding="utf-8") as fh:
        return json.load(fh)


if __name__ == "__main__":
    for n in SIZES:
        p = payload(n)
        target = path_for(n)
        with open(target, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(canonical(p))
            fh.write("\n")
        print("%s: nodes=%d edges=%d pairs=%d bytes=%d sha256=%s" % (
            os.path.basename(target), len(p["nodes"]), len(p["edges"]),
            p["shown_of"]["distinct_pairs"], os.path.getsize(target),
            sha256(p)))
