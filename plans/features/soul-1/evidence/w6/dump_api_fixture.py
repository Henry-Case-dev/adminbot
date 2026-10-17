"""SOUL-1 / W6 — генератор API-фикстуры «Речи и характера» (офлайн, без PG/LLM).

Зачем: Playwright-харнесс UI должен получать РОВНО те формы данных, которые
отдаёт реальный слой `web/api/speech.py`, а не выдуманные в тесте. Скрипт
вызывает настоящие функции эндпоинтов на изолированном ConfigCache
(in-memory) и сохраняет их ответы.

Запуск: .venv/Scripts/python.exe plans/features/soul-1/evidence/w6/dump_api_fixture.py
"""
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
from services import prompt_factory as pf  # noqa: E402
from web.api import speech as S  # noqa: E402

OUT = Path(__file__).resolve().parent / "api-fixture.json"
CHAT_ID = -1001234567890


class _AwaitResult:
    def __await__(self):
        if False:               # pragma: no cover
            yield None
        return None


class _Cache:
    def __init__(self):
        self.data = {}
        self.updated = {}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def get_updated_at(self, key):
        return self.updated.get(key)

    def set(self, key, value, category=None):
        self.data[key] = value
        self.updated[key] = "in-memory"
        return _AwaitResult()


async def _seed_real_turn_manifest(cache):
    """Манифест хода для writer Direct L2 — тем же композером, что и рантайм.

    Сидирует in-memory кэш композера ровно так, как это делает настоящий ход
    (`compose_prompt` → `_remember`) ВКЛЮЧАЯ run_id: рантайм пишет манифест с
    ``run_id=correlation_id`` (uuid хода, `direct_chat_service:4267`), поэтому
    фикстура обязана повторять эту форму — иначе зелёная витрина не
    воспроизводит рантайм (review-w6 F1). Доставки в Telegram здесь нет и не
    заявляется.
    """
    from services import prompt_composer as composer
    base = ""
    block = S.pr.by_pg_key(S.BASE_BLOCK_PG_KEY)
    if block is not None and cache is not None:
        base = str(S.pr.effective_prompt(
            block.block_id,
            pg_value=cache.get(S.BASE_BLOCK_PG_KEY, None)).text or "")
    if not base and block is not None:
        base = S.pr.factory_text(block.block_id)
    gates = composer.gates_from_config()
    run_id = uuid.uuid4().hex
    plan = composer.PromptPlan(
        profile=composer.PROFILE_SPEECH_PLAIN, writer="l2_writer", chat_id=0,
        run_id=run_id, base_prompt=base, gates=gates,
        response_plan=composer.PlanRef(text="", source="l1", extent="short"))
    manifest = composer.compose_prompt(plan)
    return manifest.manifest_id, run_id


async def main() -> int:
    cache = _Cache()
    chat_store: dict = {}

    import services.chat_params as cp

    async def get_root(chat_id, pg=None):
        store = chat_store.get(int(chat_id)) or {}
        return {"overrides": dict(store.get("overrides") or {})}

    async def set_root(chat_id, patch, **kwargs):
        store = chat_store.setdefault(int(chat_id), {})
        for ns in ("overrides", "gates", "keys", "perm_overrides", "meta"):
            if ns in patch and isinstance(patch[ns], dict):
                store[ns] = dict(patch[ns])

    cp.get_all_chat_params = get_root
    cp.set_chat_params = set_root
    pf._default_cache = lambda: cache

    ctx = SimpleNamespace(is_global_admin=True, effective_permissions=None)
    user = SimpleNamespace(id=4242)

    async def access(request, _user, x_chat_id):
        return cache, (int(x_chat_id) if x_chat_id else None), ctx

    S._access = access

    # • владельческое значение характера (то, что делает MiniApp при Save)
    factory_full = S.pr.factory_text(S.pr.CORE_FULL_BLOCK_ID)
    await S.post_block(S.pr.CORE_FULL_BLOCK_ID, None, user, S.BlockWrite(
        text=factory_full + "\n\nВладелец: держим язвительный тон, без травли."),
        None)
    # • одно правило стиля (без кавычек) и одна мягкая привычка
    preset = await S.get_style(None, user, None, "regular")
    doc = {"rules": preset["preset_documents"]["no_quotes"]["rules"],
           "soft_instructions": [
               {"id": "soft.fixture.0",
                "text": "Пиши естественными фразами, без канцелярита.",
                "scope": "global", "enabled": True}]}
    await S.post_style(None, user, S.StyleWrite(document=doc), None)
    # • настройки выражения
    await S.post_expression(None, user, S.ExpressionWrite(
        values={"wit": "high", "sharpness": "normal", "profanity": "off",
                "verbosity": "normal"}), None)

    fixture: dict = {}
    fixture["overview"] = await S.get_overview(None, user, None)
    fixture["core"] = await S.get_core(None, user, None)
    fixture["style"] = await S.get_style(None, user, None, "regular")
    fixture["expression"] = await S.get_expression(None, user, None)
    fixture["humor"] = await S.get_humor(None, user, None)
    fixture["examples"] = await S.get_examples(None, user, None)
    fixture["learning"] = await S.get_learning(None, user, None)
    fixture["capabilities"] = await S.get_capabilities(None, user, None)
    fixture["inspector"] = await S.get_inspector(None, user, None)
    # Второй вызов — уже с манифестом РЕАЛЬНОГО хода в памяти процесса:
    # композер той же сборкой (writer Direct L2) формирует снимок с
    # run_id=uuid (рантайм-форма, review-w6 F1), чтобы витрина показала ветку
    # «фактически отправлено» и её отличие от предпросмотра. Это собранный
    # payload хода, НЕ подтверждение доставки.
    manifest_id, run_id = await _seed_real_turn_manifest(cache)
    fixture["inspector_with_run"] = await S.get_inspector(None, user, None)
    if not fixture["inspector_with_run"].get("last_run_present"):
        raise SystemExit("Inspector не нашёл снимок хода с рантайм-run_id: "
                         "фикстура не воспроизводит рантайм (F1)")
    fixture["blocks"] = await S.get_blocks(None, user, None)
    fixture["block_detail"] = await S.get_block(
        S.pr.CORE_FULL_BLOCK_ID, None, user, None)
    # Реальный ответ /reset (mode=factory, apply=false) — форма
    # prompt_factory.plan_factory_reset: applies/changed + current_chars/
    # factory_chars + diff{added_lines,removed_lines}. Харнесс обязан брать
    # её отсюда, а не писать стаб руками (review-w6 F3).
    fixture["factory_reset_plan"] = await S.post_block_reset(
        S.pr.CORE_FULL_BLOCK_ID, None, user,
        S.BlockReset(mode="factory", apply=False), None)
    if not isinstance((fixture["factory_reset_plan"].get("plan") or {}).get("diff"),
                      dict):
        raise SystemExit("response /reset без реального diff: F3-фикстура пуста")
    fixture["style_preview"] = await S.post_style_preview(
        None, user, S.StylePreview(document=doc), None)
    fixture["try"] = await S.post_try(None, user, S.TryRequest(
        text="Бот, проверь «цитату» и версию 1.2.3 на https://example.org/a.",
        profile="speech_plain",
        candidate={"expression_document": {"wit": "high",
                                           "verbosity": "short"}}), None)

    OUT.write_text(json.dumps(fixture, ensure_ascii=False, indent=1),
                   encoding="utf-8", newline="\n")
    print("fixture →", OUT)
    print("sections:", ", ".join(sorted(fixture)))
    print("core edition:", fixture["core"]["editions"]["compact"]["source"],
          fixture["core"]["editions"]["compact"]["chars"], "chars")
    print("style rules:", len(fixture["style"]["rules"]),
          "hint:", fixture["style"]["hint_tokens"], "tok")
    print("inspector layers:", len(fixture["inspector"]["preview"]["layers"]))
    print("inspector run snapshot:", fixture["inspector"]["last_run_present"],
          "→", fixture["inspector_with_run"]["last_run_present"],
          "(run_id %s…)" % str(
              (fixture["inspector_with_run"].get("sent") or {}).get("run_id")
              or "?")[:8])
    fp = fixture["factory_reset_plan"]["plan"]
    print("factory reset plan: changed=%s current=%s factory=%s diff=%s"
          % (fp.get("changed"), fp.get("current_chars"), fp.get("factory_chars"),
             fp.get("diff")))
    print("capabilities:", len(fixture["capabilities"]["capabilities"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
