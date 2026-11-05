import asyncio, json, os, sys
WT = r"C:/Users/main/.config/opencode/WorkspaceData/worktrees/c742e4de9e92c489/pv-s7-review"
os.chdir(WT); sys.path.insert(0, WT)
import services.prompt_release_policy as prp
import services.prompt_registry as pr
res = dict()
async def main():
    store = prp.MemoryPromptJournal()
    long_text = "НАЧАЛО\n" + ("Очень длинный промпт с юникодом и переводом строки.\n" * 2500) + "КОНЕЦ\n"
    res["long_len"] = len(long_text)
    out = await prp.write_versioned_value("prompts.meme_joke", long_text, store=store, actor="owner")
    rid = out.get("revision_id")
    res["applied"] = out.get("applied")
    res["rev_sha_matches"] = out.get("sha256_12") == pr.sha12(long_text)
    src = await prp.get_revision_source(rid, store=store, actor="owner")
    res["roundtrip_identical"] = src.get("body") == long_text
    res["chars"] = src.get("chars")
    res["body_available"] = src.get("body_available")
    out2 = await prp.write_versioned_value("prompts.meme_joke", "ТЕКСТ ОТ НЕИЗВЕСТНОГО\n", store=store, actor="")
    res["empty_actor_applied"] = out2.get("applied")
    rows = list(store.revisions.values())
    res["actors"] = sorted(set(str(r.actor) for r in rows))
    res["created_at_all_present"] = all(bool(r.created_at) for r in rows)
asyncio.run(main())
print(json.dumps(res, ensure_ascii=False))
