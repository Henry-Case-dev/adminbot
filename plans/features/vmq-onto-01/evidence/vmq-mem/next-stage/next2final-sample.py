"""NEXT-02 final: build a FIXED stratified query set + gold labels from the
read-only production DB copy. Deterministic; no candidate/baseline output is
consulted here, so the gold set is frozen before either side runs.

Strata (contract `architecture-next2-quality.md` §"Набор запросов"):
  OLD     — question about a specific old event/fact (2022-2024 rows);
  MULTI   — multi-year participant history (same participant, facts across
            several years) -> mandatory = earliest + latest pre-2026 row;
  RECENT  — recent event where freshness matters (2026 rows with their own
            message_timestamp, newest first, chat-origin).

The corpus has NO `subject_ref_id` linkage across years (0 rows: subject ids
exist only on 2026-era rows), so MULTI is linked at TEXT level by a participant
name appearing in facts of >=3 distinct years. This is stated in the evidence.

Query text is derived mechanically from the anchor fact: the last run of
consecutive noun-like content words (1-2 words, as written in the fact) becomes
the topic phrase. No LLM is used for query construction or labelling.
"""
import collections
import datetime
import json
import re
import sqlite3

DB = (r"C:\Users\main\.config\opencode\WorkspaceData\runs\c742e4de9e92c489"
      r"\vmq-onto-01-3689dd92710d\probe-d86a98460c\prod-copy.db")
OUT = (r"C:\Users\main\.config\opencode\WorkspaceData\runs\c742e4de9e92c489"
       r"\vmq-onto-01-3689dd92710d\probe-6d16309a71\next2final-sample.json")
CHAT = -1002661910336

STOP = set("""это этот эта эти тот та те там тут так как что чтобы когда где
если или ещё еще уже очень просто тоже также надо нужно можно нельзя было
была были быть есть весь вся все всё свой своя свои своих через после перед
между около почти более менее самый самая самые такой такая такие который
которая которые которое кроме хотя пока потом затем сейчас теперь всегда
иногда вообще конечно значит может могут могла могли делать делает сделал
сделала сделали говорит говорил говорила говорили сказал сказала сказали
знает знаю знаешь думаю думает понял поняла поняли видит видел видела видели
хочет хотел хотела хотели будет будем будут будешь пойду пошел пошла пошли
пришел пришла пришли ушел ушла ушли давай давайте пусть только лишь раз два
три четыре пять много мало немного совсем очень даже ведь вот вон него неё
нее них ему ей нам вам нас вас мне тебе себя себе таки типа
""".split())

VERB_END = tuple("""ет ёт ит ют ат ят ал ял ил ыл ла ло ли ть ться тся ся ешь
ишь ует уют ает ают яет яют ится ятся атся ела ала ила ыла ело ало ило ели
али или ыл лся лась лось лись ала ались путь
""".split())

TOKEN = re.compile(r"[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё\-]+")
NAME = re.compile(r"\b([A-ZА-ЯЁ][a-zа-яё]{2,15})\b")


def is_topic(word):
    low = word.lower()
    if len(word) < 5 or low in STOP:
        return False
    if low.endswith(VERB_END):
        return False
    return True


def topic_phrase(fact):
    """Last run of 1-2 noun-like topic words, as written in the fact."""
    runs, cur = [], []
    for word in TOKEN.findall(str(fact or "")):
        if is_topic(word):
            cur.append(word)
            continue
        if cur:
            runs.append(cur)
        cur = []
    if cur:
        runs.append(cur)
    if not runs:
        return None
    phrase = runs[-1][-2:]
    phrase = [w for i, w in enumerate(phrase)
              if i == 0 or w.lower() != phrase[i - 1].lower()]
    if sum(len(w) for w in phrase) < 10:
        return None
    return " ".join(phrase)


def main():
    db = sqlite3.connect("file:%s?mode=ro&immutable=1" % DB.replace("\\", "/"),
                         uri=True)
    c = db.cursor()
    rows = c.execute(
        "select id, fact, message_timestamp, created_at, origin from "
        "graph_facts where chat_id=? and status='confirmed' order by id",
        (CHAT,)).fetchall()
    facts = []
    for fid, fact, mts, cts, origin in rows:
        ts = mts or cts
        if not ts:
            continue
        facts.append({
            "id": int(fid), "fact": str(fact or ""), "origin": origin,
            "ts": int(ts), "real_ts": bool(mts),
            "year": datetime.datetime.fromtimestamp(
                int(ts), datetime.timezone.utc).year})
    print("confirmed facts:", len(facts))

    def good_text(f):
        t = f["fact"]
        return (25 <= len(t) <= 200 and "http" not in t
                and t.count("|") == 0 and not t.startswith("[")
                and not t.startswith("<"))

    used_phrase, used_anchor = set(), set()

    def build(stratum, f, phrase, question, required_years, mandatory):
        used_phrase.add(phrase.lower())
        used_anchor.add(f["id"])
        return {"stratum": stratum, "anchor": f["id"],
                "anchor_year": f["year"], "topics": phrase.lower(),
                "question": question, "required_years": required_years,
                "mandatory": mandatory}

    def anchor_rec(f):
        return {"id": f["id"], "year": f["year"], "fact": f["fact"][:180],
                "origin": f["origin"]}

    # ── OLD: evenly spaced picks per year across 2022/2023/2024 ────────────
    per_year = {}
    for year in (2022, 2023, 2024):
        bucket = [f for f in facts
                  if f["year"] == year and f["real_ts"] and good_text(f)]
        wanted = 7 if year != 2024 else 6
        picked = []
        step = max(1, len(bucket) // max(1, wanted))
        scan = ([bucket[i] for i in range(0, len(bucket), step)]
                + [f for i, f in enumerate(bucket) if i % step])
        for f in scan:
            if len(picked) >= wanted:
                break
            phrase = topic_phrase(f["fact"])
            if phrase and phrase.lower() not in used_phrase:
                picked.append(build("old", f, phrase,
                                    "что известно про %s?" % phrase,
                                    [year], [anchor_rec(f)]))
        per_year[year] = picked
    old = [item for year in (2022, 2023, 2024) for item in per_year[year]][:20]

    # ── RECENT: newest chat-origin 2026 rows with their own timestamp ──────
    chat_origins = {"chat_history", "voice_transcript", "history_import"}
    recent_pool = [f for f in facts
                   if f["year"] == 2026 and f["real_ts"]
                   and f["origin"] in chat_origins | {"search_fact"}
                   and good_text(f)]
    # chat events first, then recent search/factcheck rows; newest first
    recent_pool.sort(key=lambda f: (0 if f["origin"] in chat_origins else 1,
                                    -f["ts"], f["id"]))
    recent = []
    for f in recent_pool:
        if len(recent) >= 20:
            break
        phrase = topic_phrase(f["fact"])
        if not phrase or phrase.lower() in used_phrase:
            continue
        recent.append(build("recent", f, phrase,
                            "что известно про %s?" % phrase,
                            [2026], [anchor_rec(f)]))

    # ── MULTI: participant name in facts of >=3 distinct years ────────────
    name_years = collections.defaultdict(set)
    name_count = collections.Counter()
    for f in facts:
        if not f["real_ts"]:
            continue
        for name in set(NAME.findall(f["fact"])):
            name_years[name].add(f["year"])
            name_count[name] += 1
    multi, used_mandatory = [], set()
    for name, yrs in sorted(name_years.items(),
                            key=lambda kv: (-len(kv[1]), -name_count[kv[0]],
                                            kv[0])):
        if len(multi) >= 20:
            break
        if len(yrs) < 3 or not (20 <= name_count[name] <= 600):
            continue
        hist = [f for f in facts if f["real_ts"] and f["year"] <= 2025
                and name in f["fact"]]
        years = sorted({f["year"] for f in hist})
        if len(years) < 3:
            continue
        first = min((f for f in hist if f["year"] == years[0]),
                    key=lambda f: f["id"])
        last = min((f for f in hist if f["year"] == years[-1]),
                   key=lambda f: f["id"])
        ids = {first["id"], last["id"]}
        if ids & used_mandatory:
            continue          # same underlying facts -> paraphrase duplicate
        used_mandatory |= ids
        multi.append(build(
            "multi", first, name,
            "что известно про %s за всё время?" % name,
            [years[0], years[-1]], [anchor_rec(first), anchor_rec(last)]))

    sample = []
    for index, item in enumerate(old):
        item["key"] = "O%02d" % (index + 1)
        sample.append(item)
    for index, item in enumerate(multi):
        item["key"] = "M%02d" % (index + 1)
        sample.append(item)
    for index, item in enumerate(recent):
        item["key"] = "R%02d" % (index + 1)
        sample.append(item)

    counts = collections.Counter(r["year"] for r in facts)
    meta = {
        "chat": CHAT,
        "corpus_confirmed_facts": len(facts),
        "corpus_year_composition": {str(k): counts[k] for k in sorted(counts)},
        "corpus_note": ("year = product `_rag_row_year` semantics "
                        "(message_timestamp or created_at); %d confirmed rows "
                        "have NULL message_timestamp and therefore fall back "
                        "to created_at (2026)" % sum(
                            1 for r in facts if not r["real_ts"])),
        "n": {"old": len(old), "multi": len(multi), "recent": len(recent)},
        "subject_ref_cross_year_linkage": 0,
        "names_spanning_3plus_years": sum(
            1 for yrs in name_years.values() if len(yrs) >= 3),
        "unique_anchors": len({q["anchor"] for q in sample}),
        "rules": {
            "old": "anchor fact 2022-2024 with its own message_timestamp, "
                   "evenly spaced per year; mandatory = anchor; "
                   "required_years = anchor year",
            "multi": "participant name in facts of >=3 distinct years; "
                     "mandatory = earliest + latest pre-2026 row; "
                     "required_years = those two years",
            "recent": "newest 2026 rows (own message_timestamp, chat-origin); "
                      "mandatory = anchor; required_years = [2026]",
            "query_template": "что известно про <topic phrase из факта>? / "
                              "что известно про <name> за всё время?",
            "relevance_rule": "old/recent: row shares >=2 distinct content "
                              "stems (len>=4) with the query; "
                              "multi: row text contains the participant name",
        },
    }
    payload = {"meta": meta, "queries": sample}
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    print("counts:", meta["n"], "unique anchors:", meta["unique_anchors"])
    for q in sample:
        print(q["key"], q["stratum"], "|", q["question"], "->",
              [(m["id"], m["year"]) for m in q["mandatory"]])
    print("wrote", OUT)


if __name__ == "__main__":
    main()
